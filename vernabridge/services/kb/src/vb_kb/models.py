"""Data models for Knowledge Base assertions.

An "assertion" is one claim from one source: this vernacular name, in this
language, in this region, refers to this scientific name. Assertions are the
atoms of the whole Knowledge Base. They are append-only: we never edit or
delete them, we add new ones that supersede old ones.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class SourceType(str, Enum):
    """Where an assertion came from. Keep this list short and meaningful."""

    CHECKLIST = "checklist"  # a published species checklist (e.g. Flora e Funga)
    WIKIDATA = "wikidata"  # Wikidata common-name statements
    AGGREGATOR = "aggregator"  # an aggregated database (e.g. Catalogue of Life)
    EXTRACTION = "extraction"  # LLM-assisted extraction from open documents (M-later)
    USER_CONFIRMATION = "user_confirmation"  # a human confirmed a match in the app
    EXPERT = "expert"  # entered directly by an expert reviewer


class VerificationStatus(str, Enum):
    """How much we trust an assertion right now."""

    UNVERIFIED = "unverified"  # imported, not yet checked by a human
    VERIFIED = "verified"  # checked by a human, or from a source we trust fully
    DISPUTED = "disputed"  # two sources disagree; needs expert review
    REJECTED = "rejected"  # a human said this is wrong (kept for the audit trail)


class Assertion(BaseModel):
    """One vernacular-name claim, with full provenance.

    Field names mirror the database schema in docs/design.md section 6.1,
    so loading these JSONL rows into Postgres later is a straight mapping.
    """

    # --- the claim itself ---
    vernacular_name: str = Field(description="The name exactly as the source wrote it")
    name_normalized: str = Field(description="Output of our normalization pipeline")
    language: str = Field(description="BCP-47 language tag, e.g. 'es', 'pt', 'es-MX'")
    script: str = Field(description="ISO 15924 script code, e.g. 'Latn', 'Deva'")
    region: str | None = Field(default=None, description="ISO 3166 code, e.g. 'BR', 'CO'")
    region_detail: str | None = Field(
        default=None,
        description="Finer place info as the source wrote it, e.g. Brazilian states 'SP, MG'",
    )
    scientific_name: str = Field(description="The scientific name the source links this name to")

    # --- taxonomy anchoring (filled by the backbone-resolve step; may be empty here) ---
    taxon_key: int | None = Field(default=None, description="GBIF backbone accepted taxonKey")
    backbone_version: str | None = Field(default=None, description="Backbone version used")

    # --- provenance: where the claim came from ---
    source_name: str = Field(description="Human-readable source name")
    source_url: str = Field(description="Where the source lives")
    source_type: SourceType
    source_record_id: str | None = Field(
        default=None, description="The record's id inside the source, for tracing back"
    )
    license: str = Field(description="License of this assertion's source, e.g. 'CC0-1.0'")
    attribution: str | None = Field(
        default=None, description="Required when the source license is CC BY"
    )

    # --- trust bookkeeping ---
    confidence: float = Field(ge=0.0, le=1.0, description="Source-level prior, 0..1")
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    contributor: str | None = Field(default=None, description="Who added/confirmed it")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("vernacular_name", "scientific_name")
    @classmethod
    def must_not_be_blank(cls, value: str) -> str:
        """A claim with an empty name on either side is meaningless — reject it early."""
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()

    def dedupe_key(self) -> tuple[str, str, str, str | None]:
        """What makes two assertions 'the same claim' for de-duplication.

        Same normalized name + language + scientific name + region = same claim.
        Different sources making the same claim is fine (it raises confidence),
        but within ONE import run we only keep the claim once.
        """
        return (self.name_normalized, self.language, self.scientific_name, self.region)


class SourceInfo(BaseModel):
    """Fixed facts about a data source, declared once per importer."""

    name: str
    url: str
    source_type: SourceType
    license: str
    attribution: str | None = None
    license_verified_on: str  # date we last checked the license, YYYY-MM-DD
    default_confidence: float  # prior for assertions from this source
