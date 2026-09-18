"""Postgres schema and the JSONL -> database loader.

This is the second half of ADR-003: importers write JSONL files, and this
module is the ONE place that writes those files into the database. Tables
mirror docs/design.md section 6.1.

Two deliberate choices (recorded as ADR-006 in DECISIONS.md):

1. **Deterministic IDs.** An assertion's id is a UUIDv5 hash of
   (source, normalized name, language, scientific name, region). Loading the
   same file twice — or the same claim arriving in two files — inserts one
   row. Re-runs are safe by construction, no clever bookkeeping needed.

2. **taxon_key may be NULL** (the design sketch said NOT NULL). Claims that
   the backbone-resolve step could not anchor with an EXACT match are still
   worth keeping — they carry provenance and go to human review — but they
   are excluded from matching until anchored. The matching queries in M2
   filter on `taxon_key IS NOT NULL`.

The models use only portable column types so tests can run on SQLite;
Postgres-only extras (pg_trgm trigram index) live in the Alembic migration.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from vb_kb.importers import REGISTRY
from vb_kb.models import Assertion, SourceInfo

# Fixed namespace for our UUIDv5 ids. Never change this value — changing it
# changes every id and breaks idempotent re-loading.
VB_NAMESPACE = uuid.UUID("b0a7c4d2-5e8f-4a91-b3c6-7d2e9f01a5b8")


def source_uuid(source_name: str) -> uuid.UUID:
    """Stable id for a source, derived from its name."""
    return uuid.uuid5(VB_NAMESPACE, f"source:{source_name}")


def assertion_uuid(assertion: Assertion) -> uuid.UUID:
    """Stable id for an assertion: same claim from the same source = same id."""
    name_norm, language, scientific_name, region = assertion.dedupe_key()
    parts = [assertion.source_name, name_norm, language, scientific_name, region or ""]
    return uuid.uuid5(VB_NAMESPACE, "assertion:" + "|".join(parts))


class Base(DeclarativeBase):
    """Declarative base for all KB tables."""


class KbSource(Base):
    """One row per data source, with its license facts (design 6.1)."""

    __tablename__ = "kb_source"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    url: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(Text)
    license: Mapped[str] = mapped_column(Text)
    attribution: Mapped[str | None] = mapped_column(Text)
    license_verified_on: Mapped[str | None] = mapped_column(Text)  # YYYY-MM-DD
    default_confidence: Mapped[float]
    notes: Mapped[str | None] = mapped_column(Text)


class KbAssertion(Base):
    """One vernacular-name claim with full provenance (design 6.1).

    Append-only: rows are never updated or deleted; a correction inserts a
    new row and points superseded_by at it.
    """

    __tablename__ = "kb_assertion"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    vernacular_name: Mapped[str] = mapped_column(Text)
    name_normalized: Mapped[str] = mapped_column(Text, index=True)
    language: Mapped[str] = mapped_column(Text, index=True)
    script: Mapped[str] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    region_detail: Mapped[str | None] = mapped_column(Text)
    scientific_name: Mapped[str] = mapped_column(Text)
    taxon_key: Mapped[int | None] = mapped_column(BigInteger, index=True)  # NULL = unanchored
    backbone_version: Mapped[str | None] = mapped_column(Text)
    backbone_match_type: Mapped[str | None] = mapped_column(Text)
    backbone_confidence: Mapped[int | None]
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_source.id"))
    source_record_id: Mapped[str | None] = mapped_column(Text)
    license: Mapped[str] = mapped_column(Text)
    attribution: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float]
    verification_status: Mapped[str] = mapped_column(Text, index=True)
    contributor: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("kb_assertion.id"))

    __table_args__ = (
        # The matching engine's first lookup: name in a language.
        Index("ix_kb_assertion_lookup", "language", "name_normalized"),
    )


class KbReview(Base):
    """Audit trail: every change of an assertion's verification status."""

    __tablename__ = "kb_review"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    assertion_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_assertion.id"), index=True)
    reviewer: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)  # e.g. 'verify', 'dispute', 'reject'
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class KbRelease(Base):
    """One row per published KB release (Zenodo DOI etc.)."""

    __tablename__ = "kb_release"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(Text, unique=True)
    zenodo_doi: Mapped[str | None] = mapped_column(Text)
    assertion_count: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def _known_sources() -> dict[str, SourceInfo]:
    """SourceInfo for every registered importer, keyed by source name."""
    return {cls.source.name: cls.source for cls in REGISTRY.values()}


@dataclass
class LoadReport:
    """Counts from one load run, for the log and for PROGRESS.md."""

    files: list[str] = field(default_factory=list)
    read: int = 0
    inserted: int = 0
    skipped_existing: int = 0  # same deterministic id already in the DB
    sources_created: int = 0


def _ensure_source(session: Session, assertion: Assertion, report: LoadReport) -> uuid.UUID:
    """Get-or-create the kb_source row for an assertion, returning its id."""
    sid = source_uuid(assertion.source_name)
    if session.get(KbSource, sid) is not None:
        return sid
    info = _known_sources().get(assertion.source_name)
    if info is not None:
        row = KbSource(
            id=sid,
            name=info.name,
            url=info.url,
            source_type=info.source_type.value,
            license=info.license,
            attribution=info.attribution,
            license_verified_on=info.license_verified_on,
            default_confidence=info.default_confidence,
            notes=None,
        )
    else:
        # A source we have no importer for (e.g. hand-curated file). Create a
        # minimal row from the assertion itself and flag it for follow-up.
        row = KbSource(
            id=sid,
            name=assertion.source_name,
            url=assertion.source_url,
            source_type=assertion.source_type.value,
            license=assertion.license,
            attribution=assertion.attribution,
            license_verified_on=None,
            default_confidence=assertion.confidence,
            notes="auto-created at load time; verify license and fill license_verified_on",
        )
    session.add(row)
    session.flush()
    report.sources_created += 1
    return sid


def load_jsonl(session: Session, path: Path, report: LoadReport, batch_size: int = 1000) -> None:
    """Load one JSONL file of assertions into the database, idempotently.

    Strategy: compute deterministic ids for a batch, SELECT which already
    exist, insert only the new ones. Plain and portable (works on SQLite in
    tests and Postgres in production) — no dialect-specific upsert needed.
    """
    report.files.append(str(path))
    batch: list[Assertion] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            batch.append(Assertion.model_validate(json.loads(line)))
            if len(batch) >= batch_size:
                _insert_batch(session, batch, report)
                batch = []
    if batch:
        _insert_batch(session, batch, report)


def _insert_batch(session: Session, batch: list[Assertion], report: LoadReport) -> None:
    """Insert one batch of assertions, skipping ids that already exist."""
    report.read += len(batch)
    ids = [assertion_uuid(a) for a in batch]
    existing: set[uuid.UUID] = set(
        session.scalars(select(KbAssertion.id).where(KbAssertion.id.in_(ids)))
    )
    seen_in_batch: set[uuid.UUID] = set()
    for assertion, aid in zip(batch, ids, strict=True):
        if aid in existing or aid in seen_in_batch:
            report.skipped_existing += 1
            continue
        seen_in_batch.add(aid)
        source_id = _ensure_source(session, assertion, report)
        session.add(
            KbAssertion(
                id=aid,
                vernacular_name=assertion.vernacular_name,
                name_normalized=assertion.name_normalized,
                language=assertion.language,
                script=assertion.script,
                region=assertion.region,
                region_detail=assertion.region_detail,
                scientific_name=assertion.scientific_name,
                taxon_key=assertion.taxon_key,
                backbone_version=assertion.backbone_version,
                backbone_match_type=assertion.backbone_match_type,
                backbone_confidence=assertion.backbone_confidence,
                source_id=source_id,
                source_record_id=assertion.source_record_id,
                license=assertion.license,
                attribution=assertion.attribution,
                confidence=assertion.confidence,
                verification_status=assertion.verification_status.value,
                contributor=assertion.contributor,
                created_at=assertion.created_at,
            )
        )
        report.inserted += 1
    session.flush()


def utcnow() -> datetime:
    """One place to get 'now' so tests can reason about it."""
    return datetime.now(UTC)
