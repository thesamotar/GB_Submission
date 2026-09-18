# VernaBridge — Update Log

Every commit gets one entry here, written in simple English so anyone joining the
project can follow what changed and why. Newest entries go on top.

Format:
- **date — short title** (commit hash once committed)
  - What changed, in plain words.
  - Why it changed.

---

- **2026-09-18 — Backbone-resolve step, Postgres schema + loader, KB stats** (commit `b50c97a`)
  - Added the step that anchors every imported name claim to GBIF's taxonomic
    backbone (the stable species numbering the whole pipeline keys on). It is
    deliberately cautious: only exact matches fill the key, synonyms resolve
    to the accepted species, and every answer is cached so re-runs are free.
  - Added the real database: the four KB tables from the design, created via
    a migration, with ids computed so that loading the same data twice can
    never create duplicates (ADR-006 explains the two small schema decisions).
  - Added `vb_kb stats` to show what is in the KB (per language, per source,
    per verification status, and how much is anchored) — from files or from
    the database. The command line covers the whole pipeline now:
    import → resolve → load → stats.
  - Why: these were the next M1 pieces after the importers. Full-size import
    runs need a network-open machine (this session's sandbox blocks the data
    APIs), but the machinery they will run through is now built and tested
    end-to-end against a real PostgreSQL 16.

- **2026-09-18 — Seed importers for Spanish and Portuguese** (commit `2d65fbb`)
  - Added the `services/kb` Python package: the data model for name claims
    ("assertions"), a name normalizer, and three plug-in importers that pull
    vernacular names from Wikidata, the Catalogue of Life, and Flora e Funga
    do Brasil. A small command-line tool runs them.
  - Every importer was tested offline (13 tests) and proven against the real
    APIs with small sample pulls (~400 assertions saved in data/samples).
  - Why: this is the start of Milestone M1 — building the open Knowledge Base
    that name matching will run against. Spanish and Portuguese go first
    (owner decision); Hindi follows once these two are fully verified.

- **2026-09-18 — Project started: M0 design document** (commit `fc7bbb9`)
  - Added `docs/design.md` (the full design), `PROGRESS.md` (running status) and
    this file.
  - Why: Milestone M0 requires a reviewed design before any production code.
