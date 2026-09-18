"""Backbone-resolve step: anchor every assertion to the GBIF taxonomic backbone.

Importers give us assertions that say "this vernacular name means this
scientific name" — but a scientific name is just a string. The whole pipeline
keys on GBIF's stable numeric taxonKey, so this module asks GBIF's
species/match service what taxonKey each scientific name maps to.

Design rules (docs/design.md section 7, stage 6):
- Target the v2 endpoint, fall back to v1 per call if v2 misbehaves.
- Synonyms resolve to the ACCEPTED taxonKey, never the synonym's own key.
- Record matchType + confidence on every assertion we touch.
- Be conservative: only an EXACT match fills taxon_key. Fuzzy and
  higher-rank matches are recorded but left unanchored for human review —
  a wrong species key in the KB is the one mistake we must not make.
- Cache every answer on disk. Names repeat constantly across sources, and
  re-runs must not hammer GBIF's API (etiquette + speed).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from vb_kb.http import get_with_retry, make_client
from vb_kb.models import Assertion

V2_URL = "https://api.gbif.org/v2/species/match"
V1_URL = "https://api.gbif.org/v1/species/match"

# Match types GBIF can return. Only EXACT is trusted to auto-fill taxon_key.
TRUSTED_MATCH_TYPES = {"EXACT"}


@dataclass
class BackboneMatch:
    """What GBIF told us about one scientific name. Stored in the cache."""

    match_type: str  # EXACT | FUZZY | HIGHERRANK | NONE | ERROR
    taxon_key: int | None  # the ACCEPTED taxonKey (synonyms already followed)
    accepted_name: str | None  # scientific name of the accepted taxon
    status: str | None  # ACCEPTED | SYNONYM | DOUBTFUL | ...
    confidence: int | None  # 0..100 as GBIF reports it
    api: str  # 'v2' or 'v1' — which endpoint answered

    @property
    def trusted(self) -> bool:
        """True when this match is good enough to anchor an assertion."""
        return self.match_type in TRUSTED_MATCH_TYPES and self.taxon_key is not None


def _as_int(value: Any) -> int | None:
    """GBIF keys arrive as int in v1 and sometimes as string in v2. Unify."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_v2(payload: dict[str, Any]) -> BackboneMatch:
    """Turn a v2 species/match response into a BackboneMatch.

    v2 shape (verified live 2026-09-18, see design.md section 2):
    the taxon is under 'usage', the accepted taxon (when the input was a
    synonym) under 'acceptedUsage', and matchType/confidence/status live
    under 'diagnostics'.
    """
    diagnostics = payload.get("diagnostics") or {}
    match_type = str(diagnostics.get("matchType") or "NONE")
    usage = payload.get("usage") or {}
    accepted = payload.get("acceptedUsage") or {}
    # Prefer the accepted taxon; fall back to the usage itself when accepted.
    chosen = accepted if accepted.get("key") is not None else usage
    return BackboneMatch(
        match_type=match_type,
        taxon_key=_as_int(chosen.get("key")),
        accepted_name=chosen.get("canonicalName") or chosen.get("name"),
        status=diagnostics.get("status"),
        confidence=_as_int(diagnostics.get("confidence")),
        api="v2",
    )


def parse_v1(payload: dict[str, Any]) -> BackboneMatch:
    """Turn a v1 species/match response into a BackboneMatch.

    v1 is flat: usageKey/acceptedUsageKey/matchType/confidence at top level.
    'acceptedUsageKey' only appears when the matched name is a synonym.
    """
    match_type = str(payload.get("matchType") or "NONE")
    taxon_key = _as_int(payload.get("acceptedUsageKey")) or _as_int(payload.get("usageKey"))
    return BackboneMatch(
        match_type=match_type,
        taxon_key=taxon_key,
        accepted_name=payload.get("canonicalName") or payload.get("scientificName"),
        status=payload.get("status"),
        confidence=_as_int(payload.get("confidence")),
        api="v1",
    )


class BackboneResolver:
    """Resolves scientific names to taxonKeys, with an on-disk cache.

    The cache is a plain JSON file mapping scientific name -> match dict.
    Plain JSON on purpose: it can be committed for fixtures, diffed in
    review, and inspected with any text editor.
    """

    def __init__(self, cache_path: Path | None = None, client: httpx.Client | None = None):
        self.cache_path = cache_path
        self.client = client or make_client()
        self.cache: dict[str, BackboneMatch] = {}
        self.api_calls = 0
        if cache_path is not None and cache_path.exists():
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
            self.cache = {name: BackboneMatch(**entry) for name, entry in raw.items()}

    def save_cache(self) -> None:
        """Write the cache back to disk (no-op when no path was given)."""
        if self.cache_path is None:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {name: asdict(match) for name, match in self.cache.items()}
        self.cache_path.write_text(
            json.dumps(serializable, ensure_ascii=False, indent=1), encoding="utf-8"
        )

    def resolve(self, scientific_name: str) -> BackboneMatch:
        """Resolve one scientific name, using the cache when possible."""
        name = scientific_name.strip()
        if name in self.cache:
            return self.cache[name]
        match = self._resolve_uncached(name)
        self.cache[name] = match
        return match

    def _resolve_uncached(self, name: str) -> BackboneMatch:
        """Ask GBIF: v2 first, v1 as the safety net (design section 7)."""
        self.api_calls += 1
        try:
            response = get_with_retry(self.client, V2_URL, params={"scientificName": name})
            return parse_v2(response.json())
        except (httpx.HTTPError, RuntimeError, ValueError):
            pass  # fall through to v1 — one endpoint being down must not stop a run
        try:
            response = get_with_retry(self.client, V1_URL, params={"name": name})
            return parse_v1(response.json())
        except (httpx.HTTPError, RuntimeError, ValueError):
            # Both endpoints failed for this name. Record the failure so the
            # run can continue; the ERROR rows are retried on the next run
            # (ERROR results are never written to the cache file — see below).
            return BackboneMatch(
                match_type="ERROR",
                taxon_key=None,
                accepted_name=None,
                status=None,
                confidence=None,
                api="none",
            )


@dataclass
class ResolveReport:
    """Counts from one resolve run, for the log and for PROGRESS.md."""

    total: int = 0
    already_anchored: int = 0  # source gave us a taxonKey (e.g. Wikidata P846)
    anchored_now: int = 0  # EXACT match filled taxon_key in this run
    left_unresolved: int = 0  # non-exact or failed; needs review, not guessing
    api_calls: int = 0


def backbone_version_stamp(api: str) -> str:
    """A honest version marker for 'which backbone answered'.

    GBIF's backbone has no simple version string in the match response, so we
    record which API answered and when. Good enough to know that two
    assertions were resolved against the same backbone snapshot or not.
    """
    return f"gbif-{api}@{datetime.now(UTC).date().isoformat()}"


def resolve_assertions(
    assertions: Iterator[Assertion],
    resolver: BackboneResolver,
    report: ResolveReport,
) -> Iterator[Assertion]:
    """Fill taxon_key for every assertion that lacks one, conservatively.

    Every row passes through (nothing is dropped): unresolved rows keep
    taxon_key=None and carry the matchType that explains why. The report
    counts what happened.
    """
    for assertion in assertions:
        report.total += 1
        if assertion.taxon_key is not None:
            report.already_anchored += 1
            yield assertion
            continue
        match = resolver.resolve(assertion.scientific_name)
        updated = assertion.model_copy(
            update={
                "backbone_match_type": match.match_type,
                "backbone_confidence": match.confidence,
            }
        )
        if match.trusted:
            updated = updated.model_copy(
                update={
                    "taxon_key": match.taxon_key,
                    "backbone_version": backbone_version_stamp(match.api),
                }
            )
            report.anchored_now += 1
        else:
            report.left_unresolved += 1
        yield updated
    # Failed lookups must not poison the cache file across runs.
    resolver.cache = {k: v for k, v in resolver.cache.items() if v.match_type != "ERROR"}
    report.api_calls = resolver.api_calls
