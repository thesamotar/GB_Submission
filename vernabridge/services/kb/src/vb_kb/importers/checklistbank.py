"""Importers backed by the ChecklistBank API (api.checklistbank.org).

ChecklistBank is GBIF + Catalogue of Life's shared home for checklist datasets.
Many of our seed sources live there behind one identical API, so one base class
serves them all — each concrete source below is just configuration.

Sources served today:
- Catalogue of Life (dataset 3LR): ~14k Spanish + ~12k Portuguese names,
  many tagged with a country. CC BY.
- Flora e Funga do Brasil (dataset 2031): ~17k Portuguese plant/fungi names,
  many tagged with Brazilian state codes ("SP, MG, ..."). CC BY.
  (Its home IPT server had no DNS record when we checked on 2026-09-18,
  so ChecklistBank is also the more reliable route for this one.)

The vernacular records reference a taxonID, so we make one extra (cached)
API call per distinct taxon to fetch the scientific name. Fine for samples
and incremental runs; bulk runs can switch to export downloads later.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx

from vb_kb.http import get_with_retry, make_client
from vb_kb.importers.base import BaseImporter
from vb_kb.models import Assertion, SourceInfo, SourceType
from vb_kb.normalize import detect_script, normalize_name

API_BASE = "https://api.checklistbank.org"
PAGE_SIZE = 500

# Our language tags (BCP-47) vs ChecklistBank's (ISO 639-3).
LANGUAGE_TO_ISO3 = {"es": "spa", "pt": "por"}


class ChecklistBankImporter(BaseImporter):
    """Base class: pulls vernacular names from one ChecklistBank dataset.

    Subclasses set `dataset_key`, `source`, `supported_languages`, and
    (when the dataset has one) `fixed_region`.
    """

    dataset_key: str
    # Set when the whole dataset is about one country (e.g. a national flora).
    fixed_region: str | None = None

    def iter_assertions(self, language: str, limit: int | None = None) -> Iterator[Assertion]:
        self.check_language(language)
        iso3 = LANGUAGE_TO_ISO3[language]
        yielded = 0
        offset = 0
        # Cache taxonID -> scientific name, because many names share a taxon.
        taxon_cache: dict[str, str | None] = {}

        with make_client(timeout_seconds=60.0) as client:
            version = self._fetch_version(client)
            while True:
                page_size = PAGE_SIZE if limit is None else min(PAGE_SIZE, limit - yielded)
                if page_size <= 0:
                    return
                response = get_with_retry(
                    client,
                    f"{API_BASE}/dataset/{self.dataset_key}/vernacular",
                    params={"language": iso3, "limit": str(page_size), "offset": str(offset)},
                )
                records = response.json().get("result") or []
                if not records:
                    return
                for record in records:
                    taxon_id = record.get("taxonID")
                    if not taxon_id or not record.get("name"):
                        continue  # a record we can't anchor is useless — skip it
                    scientific = self._scientific_name(client, str(taxon_id), taxon_cache)
                    if scientific is None:
                        continue
                    yield self.build_assertion(record, language, scientific, version)
                    yielded += 1
                    if limit is not None and yielded >= limit:
                        return
                offset += len(records)

    def build_assertion(
        self,
        record: dict[str, Any],
        language: str,
        scientific_name: str,
        version: str,
    ) -> Assertion:
        """Turn one ChecklistBank vernacular record into an Assertion.

        Pure function apart from `self` config — the unit tests call it directly.
        """
        raw_name = record["name"]
        script = detect_script(raw_name)
        # Region: a national checklist pins the country; otherwise trust the
        # record's own country tag when present. 'area' free text (e.g. Brazilian
        # state codes "SP, MG") is kept as extra detail for the matcher.
        region = self.fixed_region or record.get("country")
        return Assertion(
            vernacular_name=raw_name,
            name_normalized=normalize_name(raw_name, script),
            language=language,
            script=script,
            region=region,
            region_detail=record.get("area"),
            scientific_name=scientific_name,
            source_name=self.source.name,
            source_url=f"https://www.checklistbank.org/dataset/{self.dataset_key}",
            source_type=self.source.source_type,
            source_record_id=str(record.get("id", "")) or None,
            license=self.source.license,
            attribution=f"{self.source.attribution}, release {version}",
            confidence=self.source.default_confidence,
        )

    def _fetch_version(self, client: httpx.Client) -> str:
        """Datasets are released in versions (e.g. '2026-09-11'); record which one we read."""
        response = get_with_retry(client, f"{API_BASE}/dataset/{self.dataset_key}")
        return str(response.json().get("version", "unknown"))

    def _scientific_name(
        self,
        client: httpx.Client,
        taxon_id: str,
        cache: dict[str, str | None],
    ) -> str | None:
        """Look up the scientific name for a taxonID, with caching."""
        if taxon_id in cache:
            return cache[taxon_id]
        try:
            response = get_with_retry(
                client, f"{API_BASE}/dataset/{self.dataset_key}/taxon/{taxon_id}"
            )
            name = (response.json().get("name") or {}).get("scientificName")
        except httpx.HTTPStatusError:
            name = None  # taxon vanished between releases; skip, don't crash
        cache[taxon_id] = name
        return name


class CatalogueOfLifeImporter(ChecklistBankImporter):
    """Catalogue of Life: curated global aggregator, many country-tagged names."""

    dataset_key = "3LR"  # ChecklistBank's alias for the latest CoL release
    supported_languages = ("es", "pt")
    source = SourceInfo(
        name="Catalogue of Life",
        url="https://www.checklistbank.org/dataset/3LR",
        source_type=SourceType.AGGREGATOR,
        license="CC-BY-4.0",
        attribution="Catalogue of Life",
        license_verified_on="2026-09-18",
        default_confidence=0.8,
    )


class FloraBrasilImporter(ChecklistBankImporter):
    """Flora e Funga do Brasil: Brazil's official flora, rich in Portuguese names."""

    dataset_key = "2031"
    supported_languages = ("pt",)
    fixed_region = "BR"  # national checklist: every name is a Brazilian usage
    source = SourceInfo(
        name="Flora e Funga do Brasil",
        url="https://www.checklistbank.org/dataset/2031",
        source_type=SourceType.CHECKLIST,
        license="CC-BY-4.0",
        attribution="Flora e Funga do Brasil, Jardim Botânico do Rio de Janeiro (JBRJ)",
        license_verified_on="2026-09-18",
        default_confidence=0.9,  # national authoritative checklist
    )
