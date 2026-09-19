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
# v2 also returns VARIANT (orthographic variant) where v1 said FUZZY; neither
# is trusted, so the conservative rule holds across both APIs.
TRUSTED_MATCH_TYPES = {"EXACT"}

# Ranks we are willing to anchor an assertion to. A vernacular name pinned to a
# genus (or anything above it) is not a species claim, and the KB must not
# pretend otherwise — see the rank guard in _rank_adjusted_match_type().
ANCHORABLE_RANKS = {
    "SPECIES",
    "SUBSPECIES",
    "VARIETY",
    "SUBVARIETY",
    "FORM",
    "SUBFORM",
}


def _rank_adjusted_match_type(match_type: str, rank: str | None) -> str:
    """Downgrade an EXACT hit that landed above species to HIGHERRANK.

    Verified live 2026-09-20: v2 answers a genus-only query ("Quercus") with
    matchType EXACT and the genus key — it does NOT say HIGHERRANK the way v1's
    docs led us to expect. Taken at face value that would auto-anchor a genus
    key as if it were a species, which is exactly the mistake the design
    forbids. We normalise it here, in one place, so both parsers agree and the
    reason stays legible downstream (stats counts it as HIGHERRANK).

    An unknown rank is treated as higher-rank too: we do not anchor on a guess.
    """
    if match_type in TRUSTED_MATCH_TYPES and (rank or "").upper() not in ANCHORABLE_RANKS:
        return "HIGHERRANK"
    return match_type


@dataclass
class BackboneMatch:
    """What GBIF told us about one scientific name. Stored in the cache."""

    match_type: str  # EXACT | FUZZY | VARIANT | HIGHERRANK | NONE | ERROR
    taxon_key: int | None  # the ACCEPTED taxonKey (synonyms already followed)
    accepted_name: str | None  # scientific name of the accepted taxon
    status: str | None  # ACCEPTED | SYNONYM | DOUBTFUL | ...
    confidence: int | None  # 0..100 as GBIF reports it
    api: str  # 'v2' or 'v1' — which endpoint answered
    rank: str | None = None  # rank of the taxon we would anchor to

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

    v2 shape (re-verified live 2026-09-20): the taxon is under 'usage', the
    accepted taxon (when the input was a synonym) under 'acceptedUsage', and
    matchType/confidence under 'diagnostics'.

    Correction from that re-verification: 'diagnostics' carries only
    matchType/confidence/timeTaken/timings — there is NO 'status' there. The
    taxonomic status lives on the usage ('ACCEPTED' / 'SYNONYM'), so that is
    where we read it from; the old diagnostics lookup silently produced None
    on every row. Keys also arrive as strings in v2, which _as_int absorbs.
    """
    diagnostics = payload.get("diagnostics") or {}
    match_type = str(diagnostics.get("matchType") or "NONE")
    usage = payload.get("usage") or {}
    accepted = payload.get("acceptedUsage") or {}
    # Prefer the accepted taxon; fall back to the usage itself when accepted.
    chosen = accepted if accepted.get("key") is not None else usage
    rank = chosen.get("rank")
    # Status describes the NAME WE LOOKED UP (SYNONYM when it was a synonym),
    # so it always comes from 'usage', never from the accepted taxon.
    status = usage.get("status") or diagnostics.get("status")
    if status is None and chosen.get("key") is not None and payload.get("synonym") is not None:
        # Only infer from the top-level flag when something actually matched —
        # a NONE row carries synonym=false and must not claim to be ACCEPTED.
        status = "SYNONYM" if payload["synonym"] else "ACCEPTED"
    return BackboneMatch(
        match_type=_rank_adjusted_match_type(match_type, rank),
        taxon_key=_as_int(chosen.get("key")),
        accepted_name=chosen.get("canonicalName") or chosen.get("name"),
        status=status,
        confidence=_as_int(diagnostics.get("confidence")),
        api="v2",
        rank=rank,
    )


def parse_v1(payload: dict[str, Any]) -> BackboneMatch:
    """Turn a v1 species/match response into a BackboneMatch.

    v1 is flat: usageKey/acceptedUsageKey/matchType/confidence at top level.
    'acceptedUsageKey' only appears when the matched name is a synonym.
    """
    match_type = str(payload.get("matchType") or "NONE")
    taxon_key = _as_int(payload.get("acceptedUsageKey")) or _as_int(payload.get("usageKey"))
    rank = payload.get("rank")
    return BackboneMatch(
        match_type=_rank_adjusted_match_type(match_type, rank),
        taxon_key=taxon_key,
        accepted_name=payload.get("canonicalName") or payload.get("scientificName"),
        status=payload.get("status"),
        confidence=_as_int(payload.get("confidence")),
        api="v1",
        rank=rank,
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
    higher_rank: int = 0  # matched above species — counted inside left_unresolved
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
            if match.match_type == "HIGHERRANK":
                report.higher_rank += 1
        yield updated
    # Failed lookups must not poison the cache file across runs.
    resolver.cache = {k: v for k, v in resolver.cache.items() if v.match_type != "ERROR"}
    report.api_calls = resolver.api_calls
