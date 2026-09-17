# VernaBridge — Update Log

Every commit gets one entry here, written in simple English so anyone joining the
project can follow what changed and why. Newest entries go on top.

Format:
- **date — short title** (commit hash once committed)
  - What changed, in plain words.
  - Why it changed.

---

- **2026-09-18 — Seed importers for Spanish and Portuguese** (not yet committed)
  - Added the `services/kb` Python package: the data model for name claims
    ("assertions"), a name normalizer, and three plug-in importers that pull
    vernacular names from Wikidata, the Catalogue of Life, and Flora e Funga
    do Brasil. A small command-line tool runs them.
  - Every importer was tested offline (13 tests) and proven against the real
    APIs with small sample pulls (~400 assertions saved in data/samples).
  - Why: this is the start of Milestone M1 — building the open Knowledge Base
    that name matching will run against. Spanish and Portuguese go first
    (owner decision); Hindi follows once these two are fully verified.

- **2026-09-18 — Project started: M0 design document** (not yet committed — repo
  will be initialized when the owner asks)
  - Added `docs/design.md` (the full design), `PROGRESS.md` (running status) and
    this file.
  - Why: Milestone M0 requires a reviewed design before any production code.
