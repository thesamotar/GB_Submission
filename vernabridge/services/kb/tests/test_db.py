"""Tests for the database loader and stats. Offline, on in-memory SQLite.

The schema itself is exercised against real PostgreSQL by running the
Alembic migration (done live whenever the KB is built); these tests cover
the loader's logic: deterministic ids, idempotent re-loads, source
bookkeeping, and the stats roll-up.
"""

from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from vb_kb.db import (
    Base,
    KbAssertion,
    KbSource,
    LoadReport,
    assertion_uuid,
    load_jsonl,
    source_uuid,
)
from vb_kb.models import Assertion, SourceType
from vb_kb.stats import stats_from_db, stats_from_files


def make_assertion(name: str, language: str = "pt", region: str | None = "BR") -> Assertion:
    return Assertion(
        vernacular_name=name,
        name_normalized=name.casefold(),
        language=language,
        script="Latn",
        region=region,
        scientific_name="Pouteria caimito",
        taxon_key=2884876,
        source_name="Test checklist",
        source_url="https://example.org/checklist",
        source_type=SourceType.CHECKLIST,
        license="CC-BY-4.0",
        attribution="Example authors (2026)",
        confidence=0.9,
    )


def write_jsonl(path: Path, assertions: list[Assertion]) -> Path:
    with open(path, "w", encoding="utf-8") as handle:
        handle.writelines(assertion.model_dump_json() + "\n" for assertion in assertions)
    return path


def make_session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


# --- deterministic ids --------------------------------------------------------


def test_same_claim_same_id_different_claim_different_id() -> None:
    a = make_assertion("Abiurana")
    same = make_assertion("Abiurana")
    other_region = make_assertion("Abiurana", region="CO")
    assert assertion_uuid(a) == assertion_uuid(same)
    assert assertion_uuid(a) != assertion_uuid(other_region)
    assert source_uuid("Test checklist") == source_uuid("Test checklist")


# --- loading ------------------------------------------------------------------


def test_load_is_idempotent(tmp_path: Path) -> None:
    path = write_jsonl(
        tmp_path / "batch.jsonl", [make_assertion("Abiurana"), make_assertion("Mangaba")]
    )
    session = make_session()

    first = LoadReport()
    load_jsonl(session, path, first)
    session.commit()
    assert first.inserted == 2
    assert first.sources_created == 1

    # Loading the exact same file again must change nothing.
    second = LoadReport()
    load_jsonl(session, path, second)
    session.commit()
    assert second.inserted == 0
    assert second.skipped_existing == 2
    assert len(session.scalars(select(KbAssertion)).all()) == 2


def test_duplicate_claim_within_one_file_inserted_once(tmp_path: Path) -> None:
    path = write_jsonl(
        tmp_path / "dupes.jsonl", [make_assertion("Abiurana"), make_assertion("Abiurana")]
    )
    session = make_session()
    report = LoadReport()
    load_jsonl(session, path, report)
    assert report.inserted == 1
    assert report.skipped_existing == 1


def test_unknown_source_row_is_created_and_flagged(tmp_path: Path) -> None:
    # "Test checklist" has no registered importer, so kb_source is built from
    # the assertion itself and flagged for license follow-up.
    path = write_jsonl(tmp_path / "one.jsonl", [make_assertion("Abiurana")])
    session = make_session()
    load_jsonl(session, path, LoadReport())
    source = session.scalars(select(KbSource)).one()
    assert source.name == "Test checklist"
    assert source.license == "CC-BY-4.0"
    assert source.license_verified_on is None
    assert "auto-created" in (source.notes or "")


def test_known_source_uses_importer_source_info(tmp_path: Path) -> None:
    # An assertion whose source_name matches a registered importer gets the
    # importer's full SourceInfo (with license_verified_on) in kb_source.
    from vb_kb.importers import REGISTRY

    info = REGISTRY["wikidata"].source
    assertion = make_assertion("Sabiá").model_copy(
        update={
            "source_name": info.name,
            "source_url": info.url,
            "source_type": info.source_type,
            "license": info.license,
        }
    )
    path = write_jsonl(tmp_path / "wd.jsonl", [assertion])
    session = make_session()
    load_jsonl(session, path, LoadReport())
    source = session.scalars(select(KbSource)).one()
    assert source.name == info.name
    assert source.license_verified_on == info.license_verified_on


# --- stats ---------------------------------------------------------------------


def test_stats_agree_between_files_and_db(tmp_path: Path) -> None:
    rows = [
        make_assertion("Abiurana"),
        make_assertion("Mangaba"),
        make_assertion("Abaniquillo", language="es", region="MX").model_copy(
            update={"taxon_key": None}
        ),
    ]
    path = write_jsonl(tmp_path / "mix.jsonl", rows)

    file_stats = stats_from_files([path])
    session = make_session()
    load_jsonl(session, path, LoadReport())
    session.commit()
    db_stats = stats_from_db(session)

    for stats in (file_stats, db_stats):
        assert stats.total == 3
        assert stats.by_language["pt"] == 2
        assert stats.by_language["es"] == 1
        assert stats.anchored == 2  # the es row has no taxon_key yet
        assert stats.by_status["unverified"] == 3

    rendered = file_stats.render()
    assert "Total assertions: 3" in rendered
    assert "pt" in rendered and "es" in rendered
