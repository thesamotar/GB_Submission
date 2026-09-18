# Architecture Decision Records

Short notes on decisions we made and why, so future contributors don't have to
guess. Newest at the bottom. Format: what we decided, why, what we gave up.

## ADR-001: arq (not Celery) for background jobs

The whole system must fit a $5–10/month VM. arq is asyncio-native, needs only
Redis, and is a few hundred lines to operate. Celery is more powerful but heavier
to run and debug for a solo team. Trade-off: fewer batteries included; acceptable.

## ADR-002: SvelteKit (not Next.js) for the web app

The reverse-search page has a hard budget of <200 KB initial load on a low-end
Android over 3G. SvelteKit compiles away the framework and produces the smallest
bundles of the mainstream options. Trade-off: smaller hiring pool than React;
acceptable for this project's size.

## ADR-003: Importers stage to JSONL files before any database

Each seed importer writes newline-delimited JSON (one assertion per line) instead
of writing straight into Postgres. Why: importers stay pure and testable, can run
anywhere (no DB needed), outputs can be diffed and reviewed like code, and the
DB loading step becomes one small separate module. Trade-off: one extra step in
the pipeline; worth it for pluggability.

## ADR-004: No personal data in outbound requests

API etiquette (GBIF, Wikimedia) asks clients to be identifiable. We identify with
the repo URL, never a person's email:
`VernaBridge/x.y (+https://github.com/thesamotar/GB_Submission)`.
Decided after the owner objected to an email appearing in a User-Agent header.

## ADR-005: Sequential language rollout

Spanish and Portuguese are built and fully verified first (rich open seed data,
measurable gold sets). Only after both pass evaluation do we start Hindi, then
other languages. Why: proves the pipeline on solid ground before tackling the
scarce-data, multi-script cases. Owner decision, 2026-09-18.

## ADR-006: Deterministic assertion ids; taxon_key may be NULL

Two small deviations from the design sketch (docs/design.md 6.1), made when
building the database layer:

1. An assertion's id is a UUIDv5 hash of (source, normalized name, language,
   scientific name, region), computed in code. Same claim = same id, so
   loading a file twice — or the same claim arriving via two files — cannot
   create duplicates. Re-runs are safe by construction instead of by careful
   bookkeeping. The namespace UUID in `vb_kb/db.py` must never change.
2. The design sketch said `taxon_key NOT NULL`; the real column allows NULL.
   The backbone-resolve step only trusts EXACT matches (a wrong species key
   is the one unforgivable KB error), so honestly-unresolved claims exist and
   are worth keeping for review. Matching queries exclude them with
   `taxon_key IS NOT NULL` until a human anchors them.
