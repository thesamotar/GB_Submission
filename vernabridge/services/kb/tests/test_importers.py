"""Tests for importer parsing logic. All offline — no network calls here.

We test the pure parse functions with small fixture payloads shaped exactly
like the real APIs (copied from live responses on 2026-09-18, then trimmed).
Live behaviour is checked separately by running the CLI with --limit.
"""

import zipfile
from pathlib import Path

from vb_kb.dwca import DwcaVernacularReader
from vb_kb.importers.base import dedupe
from vb_kb.importers.checklistbank import CatalogueOfLifeImporter, FloraBrasilImporter
from vb_kb.importers.wikidata import parse_binding
from vb_kb.models import SourceType, VerificationStatus

# --- Wikidata ---------------------------------------------------------------

WIKIDATA_BINDING = {
    "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q158587"},
    "sci": {"type": "literal", "value": "Turdus rufiventris"},
    "name": {"xml:lang": "pt", "type": "literal", "value": "Sabiá-laranjeira"},
    "gbif": {"type": "literal", "value": "2490719"},
}


def test_wikidata_binding_becomes_assertion() -> None:
    assertion = parse_binding(WIKIDATA_BINDING, "pt")
    assert assertion.vernacular_name == "Sabiá-laranjeira"
    assert assertion.name_normalized == "sabiá-laranjeira"
    assert assertion.scientific_name == "Turdus rufiventris"
    assert assertion.taxon_key == 2490719  # P846 came along for free
    assert assertion.language == "pt"
    assert assertion.script == "Latn"
    assert assertion.license == "CC0-1.0"
    assert assertion.source_type == SourceType.WIKIDATA
    assert assertion.verification_status == VerificationStatus.UNVERIFIED


def test_wikidata_binding_without_gbif_id() -> None:
    binding = {k: v for k, v in WIKIDATA_BINDING.items() if k != "gbif"}
    assertion = parse_binding(binding, "pt")
    assert assertion.taxon_key is None  # backbone-resolve step will fill this later


# --- ChecklistBank (Catalogue of Life + Flora e Funga do Brasil) -------------

COL_RECORD = {
    "id": 84125,
    "name": "Abaniquillo Adornado de Chiapas",
    "language": "spa",
    "country": "MX",
    "taxonID": "5V5LR",
}

FLORA_RECORD = {
    "id": 6616,
    "name": "Abiurana",
    "language": "por",
    "area": "SP, MG, MT, MS, GO, DF",
    "taxonID": "14518",
}


def test_col_record_becomes_assertion() -> None:
    importer = CatalogueOfLifeImporter()
    assertion = importer.build_assertion(COL_RECORD, "es", "Anolis ornatus", "2026-09-11")
    assert assertion.vernacular_name == "Abaniquillo Adornado de Chiapas"
    assert assertion.region == "MX"  # CoL's country tag is preserved
    assert assertion.scientific_name == "Anolis ornatus"
    assert assertion.license == "CC-BY-4.0"
    assert "2026-09-11" in (assertion.attribution or "")  # release version is credited


def test_flora_brasil_record_becomes_assertion() -> None:
    importer = FloraBrasilImporter()
    assertion = importer.build_assertion(FLORA_RECORD, "pt", "Pouteria caimito", "2026-08-01")
    assert assertion.region == "BR"  # national checklist pins the country
    assert assertion.region_detail == "SP, MG, MT, MS, GO, DF"  # states preserved for matching
    assert assertion.confidence == 0.9  # authoritative national source


# --- Flora e Funga do Brasil (generic DwC-A reader) -------------------------

META_XML = """<?xml version="1.0"?>
<archive xmlns="http://rs.tdwg.org/dwc/text/">
  <core rowType="http://rs.tdwg.org/dwc/terms/Taxon" fieldsTerminatedBy="\\t"
        linesTerminatedBy="\\n" encoding="utf-8" ignoreHeaderLines="1">
    <files><location>taxon.txt</location></files>
    <id index="0"/>
    <field index="1" term="http://rs.tdwg.org/dwc/terms/scientificName"/>
  </core>
  <extension rowType="http://rs.gbif.org/terms/1.0/VernacularName"
             fieldsTerminatedBy="\\t" linesTerminatedBy="\\n" encoding="utf-8"
             ignoreHeaderLines="1">
    <files><location>vernacularname.txt</location></files>
    <coreid index="0"/>
    <field index="1" term="http://rs.tdwg.org/dwc/terms/vernacularName"/>
    <field index="2" term="http://purl.org/dc/terms/language"/>
  </extension>
</archive>
"""

TAXON_TXT = "id\tscientificName\n101\tHancornia speciosa\n102\tTurdus rufiventris\n"
VERNACULAR_TXT = (
    "coreid\tvernacularName\tlanguage\n"
    "101\tMangaba\tPORTUGUES\n"
    "102\tSabiá-laranjeira\tpt\n"
    "999\tOrphan name\tpt\n"  # no matching taxon: must be skipped, not crash
)


def make_test_archive(tmp_path: Path) -> Path:
    """Build a tiny but valid DwC archive zip for testing. Synthetic data, labelled."""
    path = tmp_path / "test_archive.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("meta.xml", META_XML)
        archive.writestr("taxon.txt", TAXON_TXT)
        archive.writestr("vernacularname.txt", VERNACULAR_TXT)
    return path


def test_dwca_reader_joins_names_to_taxa(tmp_path: Path) -> None:
    reader = DwcaVernacularReader(make_test_archive(tmp_path))
    rows = list(reader.iter_rows())
    assert ("Mangaba", "PORTUGUES", "Hancornia speciosa") in rows
    assert ("Sabiá-laranjeira", "pt", "Turdus rufiventris") in rows
    assert len(rows) == 2  # the orphan row was skipped quietly


# --- de-duplication ---------------------------------------------------------


def test_dedupe_drops_repeated_claims() -> None:
    first = parse_binding(WIKIDATA_BINDING, "pt")
    duplicate = parse_binding(WIKIDATA_BINDING, "pt")
    result = list(dedupe(iter([first, duplicate])))
    assert len(result) == 1
