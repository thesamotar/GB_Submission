# VernaBridge — Progress

Simple running log of where the project stands. Newest on top.

## 2026-09-20 — Live re-verification of the GBIF v2 parser; first large import

**Fixed — two real bugs, both found by checking the parser against the live API**
- **Genus-level matches would have been auto-anchored as species.** Live v2
  answers a genus-only query ("Quercus") with `matchType: EXACT` and the genus
  key — it does NOT report HIGHERRANK the way v1 did. Taken at face value that
  silently defeats the design rule that only species-or-below EXACT matches may
  fill `taxon_key`. `backbone.py` now carries a rank guard that downgrades any
  EXACT hit above species rank to HIGHERRANK, in one shared place so v1 and v2
  agree; an unknown rank is treated as higher-rank too (never anchor on a guess).
- **`status` was never captured from v2.** The parser read `diagnostics.status`;
  the live `diagnostics` holds only matchType/confidence/timeTaken/timings, and
  the status lives on `usage`. Every v2-resolved row silently carried None.
- The offline fixtures had encoded that same wrong shape, so the tests passed
  while agreeing with the bug. Fixtures corrected against live responses
  (including v2's string-typed keys), regression tests added for both. Also
  recorded: v2 says VARIANT where v1 said FUZZY — untrusted either way, so the
  conservative rule held there. `resolve` now reports how many rows were
  rejected for rank, so the drop is visible rather than silent.
- 32 tests (was 28), ruff + mypy --strict clean.

**Verified live** (this machine has open network; the 2026-09-18 session did not)
- All five importer x language combos pull: wikidata es/pt, col es/pt,
  flora-brasil pt. A 200-row COL Spanish sample resolved 99.5% anchored.
- Whole pipeline exercised end to end except `load`: import -> resolve -> stats.

**First large import — PARTIAL, 77,057 rows in `data/runs/` (gitignored)**
- Complete: wikidata es 27,598 / wikidata pt 22,250 / col es 13,150 /
  col pt 12,304. 40,748 es + 36,309 pt; 63.3% arrive pre-anchored via
  Wikidata P846, needing no backbone lookup at all.
- **Incomplete: flora-brasil pt stopped at 1,755 of ~16,920** — do not treat
  that source's count as final. Re-run it to top up; dedupe absorbs the overlap.
- Measured rates, for planning: Wikidata ~76 rows/sec, but ChecklistBank
  (COL, flora-brasil) ~5.5 rows/sec — COL Spanish alone took 39 minutes.
  Backbone-resolve runs ~5.2 GBIF calls/sec, so a full resolve over this
  dataset is roughly 2 hours. It is resumable: the cache is saved even if the
  run is killed, and cached names cost zero calls on re-run.

**In progress / next**
- `vb_kb load` and stats-from-DB are still UNVERIFIED on real data: this
  machine has neither Postgres nor Docker. Decision (owner, 2026-09-20): point
  it at an existing Supabase project rather than installing Postgres. Put the
  DSN in gitignored `.env` as `VB_DB_DSN` (see `.env.example`) — use the DIRECT
  connection on port 5432, not the transaction pooler on 6543, which will not
  run Alembic migrations.
- Finish the flora-brasil import; then the full backbone-resolve.
- First evaluation gold sets; Zenodo release packaging.

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
