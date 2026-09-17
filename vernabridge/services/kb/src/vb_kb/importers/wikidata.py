"""Importer: Wikidata taxon common names.

Wikidata stores "taxon common name" statements (property P1843) on taxon items,
and many items also carry a GBIF taxon ID (property P846) — which saves us a
GBIF lookup later. All Wikidata data is CC0.

Measured coverage (2026-09-18): Spanish 32,202 names, Portuguese 23,159.

We query the public SPARQL endpoint in pages. Community-edited data is good
but not curated, so assertions get a middling confidence prior and stay
'unverified' until reviewed.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from vb_kb.http import get_with_retry, make_client
from vb_kb.importers.base import BaseImporter
from vb_kb.models import Assertion, SourceInfo, SourceType
from vb_kb.normalize import detect_script, normalize_name

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
PAGE_SIZE = 2000

# No ORDER BY on purpose: sorting the whole result set makes the endpoint
# time out (502) on big languages. Without it, LIMIT/OFFSET paging is not
# perfectly stable — rare duplicates across pages are absorbed by dedupe(),
# and rare misses are acceptable for seeding (the full import re-runs and
# tops up). If we ever need exactness, switch to the Wikidata JSON dump.
QUERY_TEMPLATE = """
SELECT ?item ?sci ?name ?gbif WHERE {{
  ?item wdt:P225 ?sci .
  ?item wdt:P1843 ?name .
  FILTER(LANG(?name) = "{lang}")
  OPTIONAL {{ ?item wdt:P846 ?gbif }}
}}
LIMIT {limit} OFFSET {offset}
"""


def parse_binding(binding: dict[str, Any], language: str) -> Assertion:
    """Turn one SPARQL result row into an Assertion. Pure function — easy to test."""
    raw_name = binding["name"]["value"]
    scientific = binding["sci"]["value"]
    item_url = binding["item"]["value"]  # e.g. http://www.wikidata.org/entity/Q1071795

    # P846 is GBIF's taxon id as a string; keep it only if it's a clean integer.
    taxon_key: int | None = None
    if "gbif" in binding:
        gbif_raw = binding["gbif"]["value"]
        if gbif_raw.isdigit():
            taxon_key = int(gbif_raw)

    script = detect_script(raw_name)
    return Assertion(
        vernacular_name=raw_name,
        name_normalized=normalize_name(raw_name, script),
        language=language,
        script=script,
        region=None,  # Wikidata P1843 has no reliable region qualifier
        scientific_name=scientific,
        taxon_key=taxon_key,
        source_name="Wikidata",
        source_url=item_url,
        source_type=SourceType.WIKIDATA,
        source_record_id=item_url.rsplit("/", 1)[-1],
        license="CC0-1.0",
        attribution=None,  # CC0 needs none
        confidence=0.6,
    )


class WikidataImporter(BaseImporter):
    """Pulls taxon common names for one language from Wikidata."""

    source = SourceInfo(
        name="Wikidata",
        url="https://www.wikidata.org",
        source_type=SourceType.WIKIDATA,
        license="CC0-1.0",
        attribution=None,
        license_verified_on="2026-09-18",
        default_confidence=0.6,
    )
    supported_languages = ("es", "pt")

    def iter_assertions(self, language: str, limit: int | None = None) -> Iterator[Assertion]:
        self.check_language(language)
        yielded = 0
        offset = 0
        with make_client(timeout_seconds=120.0) as client:
            while True:
                page_size = PAGE_SIZE if limit is None else min(PAGE_SIZE, limit - yielded)
                if page_size <= 0:
                    return
                query = QUERY_TEMPLATE.format(lang=language, limit=page_size, offset=offset)
                response = get_with_retry(
                    client,
                    SPARQL_ENDPOINT,
                    params={"query": query, "format": "json"},
                )
                bindings = response.json()["results"]["bindings"]
                if not bindings:
                    return  # no more data
                for binding in bindings:
                    yield parse_binding(binding, language)
                    yielded += 1
                offset += len(bindings)
