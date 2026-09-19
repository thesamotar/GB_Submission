# VernaBridge — Update Log

Every commit gets one entry here, written in simple English so anyone joining the
project can follow what changed and why. Newest entries go on top.

Format:
- **date — short title** (commit hash once committed)
  - What changed, in plain words.
  - Why it changed.

---

- **2026-09-20 — Fixed two backbone-matching bugs found against the live GBIF API** (commit `d5537d2`)
  - We finally ran the name-matching code against the real GBIF service (the
    previous session's machine had no internet access to it). Two things were
    wrong, and both mattered.
  - First and most serious: when you look up a name that is only a genus — a
    group of species rather than one species — GBIF now answers "exact match".
    Our code trusted that and would have pinned common names to a whole genus
    as though it were a single species. That is the one kind of mistake this
    project must never make, so the code now checks what LEVEL the match came
    back at and refuses to anchor anything coarser than a species.
  - Second: we were reading each name's taxonomic status (is this the accepted
    name, or an older synonym?) from the wrong part of the response, so it came
    back empty every time. Now read from the right place.
  - Our offline tests had been written from the same mistaken idea of the
    response, so they happily agreed with the bug. They have been rewritten
    from real responses, with new tests pinning down both failures. 32 tests
    pass; lint and type checks clean.
  - Also added `.env.example` and started ignoring `.env`, so database
    passwords have an obvious home outside the repo.
  - Why: this was the "re-verify against the live API before the first full
    run" item on the watch list — it earned its keep. Running the full data
    load first would have filled the KB with tens of thousands of wrong,
    too-coarse links.

- **2026-09-18 — Backbone-resolve step, Postgres schema + loader, KB stats** (commit `0618b13`)
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
