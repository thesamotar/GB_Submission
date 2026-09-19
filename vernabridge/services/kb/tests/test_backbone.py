"""Tests for the backbone-resolve step. All offline — no network calls.

Fixture payloads are shaped like the real GBIF responses. The v2 fixtures were
CORRECTED on 2026-09-20 against live api.gbif.org responses: the earlier ones
put 'status' inside 'diagnostics', where the real API never puts it, and had no
case for a genus-level hit. Live behaviour is re-checked by running the CLI
against the real API whenever the network allows.
"""

import json
from pathlib import Path

import httpx

from vb_kb.backbone import (
    BackboneResolver,
    ResolveReport,
    parse_v1,
    parse_v2,
    resolve_assertions,
)
from vb_kb.models import Assertion, SourceType

# --- response parsing ---------------------------------------------------------

V2_EXACT_ACCEPTED = {
    "synonym": False,
    "usage": {
        "key": "2490719",  # v2 returns keys as STRINGS
        "name": "Turdus rufiventris Vieillot, 1818",
        "canonicalName": "Turdus rufiventris",
        "rank": "SPECIES",
        "status": "ACCEPTED",  # status lives here, NOT in diagnostics
    },
    "classification": [{"key": "1", "name": "Animalia", "rank": "KINGDOM"}],
    "diagnostics": {"matchType": "EXACT", "confidence": 100, "timeTaken": 1},
}

V2_EXACT_SYNONYM = {
    "synonym": True,
    "usage": {
        "key": "5333294",
        "canonicalName": "Achras caimito",
        "rank": "SPECIES",
        "status": "SYNONYM",
    },
    "acceptedUsage": {"key": "2884876", "canonicalName": "Pouteria caimito", "rank": "SPECIES"},
    "diagnostics": {"matchType": "EXACT", "confidence": 99, "timeTaken": 1},
}

# A genus-only query. Live v2 answers EXACT with the GENUS key — it does not
# say HIGHERRANK. Anchoring this would put a genus key on a species claim.
V2_GENUS_EXACT = {
    "synonym": False,
    "usage": {
        "key": "2877951",
        "canonicalName": "Quercus",
        "rank": "GENUS",
        "status": "ACCEPTED",
    },
    "diagnostics": {"matchType": "EXACT", "confidence": 94, "timeTaken": 1},
}

# Live v2 calls an orthographic misspelling VARIANT where v1 says FUZZY.
V2_VARIANT = {
    "synonym": False,
    "usage": {
        "key": "2878688",
        "canonicalName": "Quercus robur",
        "rank": "SPECIES",
        "status": "ACCEPTED",
    },
    "diagnostics": {"matchType": "VARIANT", "confidence": 95, "timeTaken": 1},
}

V2_NONE = {"synonym": False, "diagnostics": {"matchType": "NONE", "confidence": 100}}

V1_EXACT = {
    "usageKey": 2490719,
    "scientificName": "Turdus rufiventris Vieillot, 1818",
    "canonicalName": "Turdus rufiventris",
    "status": "ACCEPTED",
    "confidence": 99,
    "matchType": "EXACT",
    "rank": "SPECIES",
    "synonym": False,
}

V1_SYNONYM = {
    "usageKey": 5333294,
    "acceptedUsageKey": 2884876,
    "canonicalName": "Achras caimito",
    "status": "SYNONYM",
    "confidence": 98,
    "matchType": "EXACT",
    "rank": "SPECIES",
    "synonym": True,
}

V1_FUZZY = {
    "usageKey": 2490719,
    "canonicalName": "Turdus rufiventris",
    "status": "ACCEPTED",
    "confidence": 80,
    "matchType": "FUZZY",
    "rank": "SPECIES",
    "synonym": False,
}


def test_v2_exact_accepted() -> None:
    match = parse_v2(V2_EXACT_ACCEPTED)
    assert match.trusted
    assert match.taxon_key == 2490719
    assert match.accepted_name == "Turdus rufiventris"
    assert match.api == "v2"
    assert match.rank == "SPECIES"


def test_v2_reads_status_from_usage_not_diagnostics() -> None:
    # Regression: the live API has no diagnostics.status, so reading it there
    # left every v2 row with status=None.
    assert parse_v2(V2_EXACT_ACCEPTED).status == "ACCEPTED"
    assert parse_v2(V2_EXACT_SYNONYM).status == "SYNONYM"


def test_v2_synonym_resolves_to_accepted_key() -> None:
    match = parse_v2(V2_EXACT_SYNONYM)
    assert match.taxon_key == 2884876  # the ACCEPTED taxon, not the synonym
    assert match.accepted_name == "Pouteria caimito"


def test_v2_genus_exact_is_not_anchored() -> None:
    # Regression: v2 says EXACT for a genus-only hit. Anchoring it would pin a
    # vernacular name to a genus key as though it were a species.
    match = parse_v2(V2_GENUS_EXACT)
    assert match.rank == "GENUS"
    assert match.match_type == "HIGHERRANK"
    assert not match.trusted


def test_v2_variant_is_recorded_but_not_trusted() -> None:
    match = parse_v2(V2_VARIANT)
    assert match.match_type == "VARIANT"
    assert not match.trusted


def test_v1_higher_rank_is_not_anchored() -> None:
    match = parse_v1({**V1_EXACT, "rank": "GENUS"})
    assert match.match_type == "HIGHERRANK"
    assert not match.trusted


def test_v2_none_is_not_trusted() -> None:
    match = parse_v2(V2_NONE)
    assert match.match_type == "NONE"
    assert match.taxon_key is None
    assert not match.trusted
    assert match.status is None  # a no-match row must not claim ACCEPTED


def test_v1_exact_and_synonym() -> None:
    assert parse_v1(V1_EXACT).taxon_key == 2490719
    assert parse_v1(V1_SYNONYM).taxon_key == 2884876  # acceptedUsageKey wins


def test_fuzzy_match_is_recorded_but_not_trusted() -> None:
    match = parse_v1(V1_FUZZY)
    assert match.match_type == "FUZZY"
    assert not match.trusted  # a fuzzy hit never auto-anchors an assertion


# --- resolver behaviour (mocked HTTP) ----------------------------------------


def make_assertion(scientific_name: str, taxon_key: int | None = None) -> Assertion:
    return Assertion(
        vernacular_name="sabiá-laranjeira",
        name_normalized="sabiá-laranjeira",
        language="pt",
        script="Latn",
        scientific_name=scientific_name,
        taxon_key=taxon_key,
        source_name="Test source",
        source_url="https://example.org",
        source_type=SourceType.CHECKLIST,
        license="CC0-1.0",
        confidence=0.9,
    )


def mock_resolver(handler: httpx.MockTransport, cache_path: Path | None = None) -> BackboneResolver:
    client = httpx.Client(transport=handler)
    return BackboneResolver(cache_path=cache_path, client=client)


def test_resolver_uses_v2_and_caches(tmp_path: Path) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json=V2_EXACT_ACCEPTED)

    resolver = mock_resolver(httpx.MockTransport(handler), tmp_path / "cache.json")
    first = resolver.resolve("Turdus rufiventris")
    second = resolver.resolve("Turdus rufiventris")  # cache hit, no second call
    assert first.taxon_key == second.taxon_key == 2490719
    assert len(calls) == 1
    assert "/v2/" in calls[0]

    # The cache file round-trips: a fresh resolver needs no network at all.
    resolver.save_cache()
    reloaded = mock_resolver(httpx.MockTransport(handler), tmp_path / "cache.json")
    assert reloaded.resolve("Turdus rufiventris").taxon_key == 2490719
    assert len(calls) == 1


def test_resolver_falls_back_to_v1_when_v2_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/v2/" in str(request.url):
            return httpx.Response(404)  # v2 unavailable — must not kill the run
        return httpx.Response(200, json=V1_EXACT)

    match = mock_resolver(httpx.MockTransport(handler)).resolve("Turdus rufiventris")
    assert match.api == "v1"
    assert match.taxon_key == 2490719


def test_resolve_assertions_fills_only_trusted_matches(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.params.get("scientificName") or request.url.params.get("name")
        if name == "Turdus rufiventris":
            return httpx.Response(200, json=V2_EXACT_ACCEPTED)
        return httpx.Response(200, json=V2_NONE)

    resolver = mock_resolver(httpx.MockTransport(handler))
    rows = [
        make_assertion("Turdus rufiventris"),  # will anchor
        make_assertion("Nonexistus imaginarius"),  # NONE: stays unanchored
        make_assertion("Turdus rufiventris", taxon_key=42),  # already anchored: untouched
    ]
    report = ResolveReport()
    resolved = list(resolve_assertions(iter(rows), resolver, report))

    assert resolved[0].taxon_key == 2490719
    assert resolved[0].backbone_match_type == "EXACT"
    assert resolved[0].backbone_version is not None
    assert resolved[1].taxon_key is None  # never guess
    assert resolved[1].backbone_match_type == "NONE"
    assert resolved[2].taxon_key == 42  # source-provided keys are left alone
    assert report.total == 3
    assert report.anchored_now == 1
    assert report.left_unresolved == 1
    assert report.already_anchored == 1


def test_failed_lookups_are_not_written_to_cache(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400)  # both APIs reject us

    cache_path = tmp_path / "cache.json"
    resolver = mock_resolver(httpx.MockTransport(handler), cache_path)
    report = ResolveReport()
    resolved = list(resolve_assertions(iter([make_assertion("Broken name")]), resolver, report))
    resolver.save_cache()

    assert resolved[0].backbone_match_type == "ERROR"
    assert report.left_unresolved == 1
    # ERROR must not persist — the next run should retry this name.
    assert json.loads(cache_path.read_text()) == {}
