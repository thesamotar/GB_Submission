# VernaBridge — Progress

Simple running log of where the project stands. Newest on top.

## 2026-09-18 — M1 continued: backbone-resolve + Postgres loading + stats

**Built**
- Backbone-resolve step (`vb_kb/backbone.py`): anchors every assertion to a
  GBIF accepted taxonKey via species/match v2 (v1 fallback per call).
  Conservative by design: only EXACT matches auto-fill; synonyms resolve to
  the accepted taxon; matchType + confidence recorded on every row; answers
  cached on disk so re-runs cost zero API calls.
- Postgres layer (`vb_kb/db.py` + Alembic): kb_source / kb_assertion /
  kb_review / kb_release per design 6.1, deterministic UUIDv5 ids so loading
  is idempotent (ADR-006), pg_trgm trigram index ready for M2 fuzzy recall.
  Migration applied and verified against a real PostgreSQL 16.
- `vb_kb stats`: per-language / per-source / per-status counts with backbone
  fill-rate, from JSONL files or from the database. This is the "what's in
  the KB" view until the web app exists — no frontend needed in M1.
- CLI now covers the whole pipeline: import → resolve → load → stats.
- 28 offline tests total (15 new), ruff + mypy --strict clean. End-to-end
  proven live in-session: fixture JSONL loaded twice into Postgres 16
  (second load: 0 inserted, 3 skipped — idempotency holds), stats read back,
  trigram similarity query answered from the new index.

**In progress / next**
- Full import runs (~45k es/pt assertions) + backbone-resolve + load, on a
  machine with open network access (this session's sandbox blocks
  api.gbif.org / query.wikidata.org / api.checklistbank.org, so full runs
  and live re-verification of the v2 response shape wait for that).
- First evaluation gold sets; Zenodo release packaging.

**Known issues / watch list**
- The v2 species/match parser is built from the shape verified live on
  2026-09-18 (design 2) and covered by offline fixtures; re-verify against
  the live API on the next network-open session before the first full run.
- Owner note (2026-09-18): database download for verification deferred —
  working from iPad; verify counts after the first full import run instead.

## 2026-09-18 — M1 started: seed importers working (Spanish + Portuguese)

**Built**
- `services/kb` Python package: assertion data model with full provenance,
  import-time normalizer (NFC, script detection, idempotent — property-tested),
  polite shared HTTP client (retry/backoff, no personal data in headers),
  pluggable importer framework with a registry, and a CLI.
- Three working importers, each proven with a live sample pull:
  - `wikidata` (CC0) — es + pt; ~89% of sampled rows already carry a GBIF
    taxonKey via Wikidata property P846, saving backbone lookups later.
  - `col` (Catalogue of Life via ChecklistBank, CC BY) — es + pt; many names
    carry a country tag (used for geographic weighting in M2).
  - `flora-brasil` (Flora e Funga do Brasil via ChecklistBank, CC BY) — pt;
    16,920 Portuguese names available, many tagged with Brazilian state codes.
- 13 offline tests, ruff + mypy --strict clean.
- Generic Darwin Core Archive reader (`vb_kb/dwca.py`), tested, ready for
  sources that only publish DwC-A files.

**Decisions this session** (details in DECISIONS.md)
- ADR-005: Spanish + Portuguese first; Hindi starts only after both verify.
- Owner set the repo: https://github.com/thesamotar/GB_Submission

**In progress / next**
- Full import runs (all ~45k es/pt assertions), backbone-resolve step,
  Postgres loading, first evaluation gold sets.

**Known issues / watch list**
- Wikidata SPARQL cannot ORDER BY on big result sets (times out) — paging is
  slightly unstable; dedupe absorbs it, full runs verify counts.
- ipt.jbrj.gov.br (Flora e Funga home server) had no DNS record on 2026-09-18;
  ChecklistBank route works and is the primary.
- GBIF's `/dataset/{key}/document` endpoint returns the EML metadata, NOT the
  archive — don't repeat that mistake.

## 2026-09-18 — M0: Design

**Built**
- `docs/design.md` — full M0 design: measured evidence of the vernacular-name gap,
  pilot language selection (Spanish, Portuguese, Hindi; Swahili deferred),
  architecture, KB schema, matching-pipeline spec with thresholds, competitive
  review, budget-matched deploy plan, ranked risks.
- Live API verification done: GBIF species/match v1 and v2 both work; Wikidata and
  Catalogue of Life vernacular coverage measured per language; seed-source
  licenses confirmed via the GBIF dataset registry.

**In progress**
- Nothing — waiting for owner approval of M0 (gate before any production code).

**Deferred**
- Swahili and Chinese pilots (phase 2).
- IPT plugin for other tool builders (post-M4).

**Known issues / watch list**
- India Biodiversity Portal blocks non-browser clients; use their GBIF-published
  datasets only.
- Partner outreach (owner) is the M6 critical path — start during M1.
