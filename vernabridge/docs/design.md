# VernaBridge — M0 Design Document

**Status:** Draft for approval (Milestone M0 — no production code yet)
**Date:** 2026-09-18
**Target:** 2027 GBIF Ebbe Nielsen Challenge
**Authors:** Abhishek (owner) + Claude (lead engineer)

This document is written in simple English on purpose. New team members should be
able to read it top to bottom and understand what we are building and why.

---

## 1. What VernaBridge is, in one paragraph

Huge amounts of biodiversity data around the world are written down using local
(vernacular) species names — community forest registers, school bio-blitzes, NGO
surveys, fisher logbooks. This data cannot enter GBIF today because nothing turns
"महुआ, 12 trees, near the river, June" into a valid Darwin Core record. VernaBridge
is the missing on-ramp: it takes a spreadsheet or a photo of a paper register,
resolves the local names to scientific names (carefully, with a human confirming
anything uncertain), fills in places and dates, screens for sensitive species,
and produces a valid Darwin Core Archive published under the community's own name.

## 2. Evidence the gap is real (measured live, 2026-09-18)

We did not assume the gap — we measured it against the live APIs:

| Source | Spanish | Portuguese | French | Chinese | Indonesian | Tamil | Bengali | **Hindi** | **Swahili** |
|---|---|---|---|---|---|---|---|---|---|
| Wikidata taxon common names (P1843) | 32,202 | 23,159 | 25,306 | 126,753+ | 1,799 | 221 | 134 | **124** | **47** |
| Catalogue of Life vernaculars (ChecklistBank, dataset 3LR) | 14,159 | 12,324 | 12,014 | 2,237 | 50 | 30 | 7 | **8** | **3** |

Two concrete spot checks:

- **Mango** (*Mangifera indica*, GBIF taxonKey 3190638) — one of the most famous
  trees in India — has vernacular names in GBIF in English, Malay, German, French,
  Portuguese, Spanish, Swedish and Khmer. **Not one Indian language.**
- Searching GBIF's vernacular index for **आम** (Hindi for mango, Devanagari script)
  returns 4 records total, all genus/family level.

So: Hindi (~600M speakers) has 8 vernacular names in Catalogue of Life. Swahili
(~80M speakers) has 3. This is both our problem statement and our headline stat
for the Challenge entry.

API facts verified the same day:

- `GET https://api.gbif.org/v1/species/match?name=...` works (returns usageKey,
  matchType, confidence).
- `GET https://api.gbif.org/v2/species/match?scientificName=...` also works and
  returns richer diagnostics (per-step timings, additional status such as IUCN
  dataset flags). We will target **v2** with a v1 fallback, and re-verify before M2.
- Licenses read from the GBIF dataset registry (machine-readable, not guessed):
  - India Biodiversity Portal publication-grade dataset — **CC BY 4.0**
  - Flora e Funga do Brasil, Lista Oficial — **CC BY 4.0**
  - Catálogo de Plantas y Líquenes de Colombia (SiB Colombia) — **CC BY 4.0**
  - CONABIO (Mexico) taxonomic checklists — **CC0 / CC BY 4.0** (varies per list)
- The India Biodiversity Portal website blocks non-browser clients (Cloudflare).
  Their data reaches us reliably through their GBIF-published datasets instead.
  Direct portal scraping is off the table (license etiquette + technical block).

## 3. Pilot languages (evidence-driven choice)

The owner's instruction: pick pilots where datasets actually exist for testing.
The honest answer is a **two-tier design**, because "data to seed the knowledge
base" and "data that proves the tool matters" pull in opposite directions:

### Tier 1 — rich-seed pilots (prove the pipeline end-to-end with real open data)

**Pilot 1: Spanish (Colombia + Mexico).**
- Script: Latin. Normalization: lowercase, NFC, keep diacritics but match
  accent-insensitively (ñ is significant, á/a is not — configurable per language).
- Seed sources (license verified above): SiB Colombia Catálogo (CC BY 4.0),
  CONABIO/EncicloVida checklists (CC0/CC BY 4.0), Wikidata (CC0, 32K names),
  Catalogue of Life (14K names).
- Why it stress-tests us: strong **regional homonymy** — the same Spanish name
  means different species in Mexico vs Colombia vs Argentina. This is the test
  bed for geographic weighting.
- Gold set plan: 300–500 name→taxon pairs sampled from a source we deliberately
  keep OUT of the seed KB (e.g. hold out one CONABIO group checklist), plus
  regional homonyms curated by hand. Both Mexico and Colombia regions represented.
- Candidate partners: SiB Colombia (GBIF node), CONABIO (GBIF node).

**Pilot 2: Portuguese (Brazil).**
- Script: Latin. Normalization like Spanish (cedilla, tildes).
- Seed sources: Flora e Funga do Brasil (CC BY 4.0, includes "nomes populares"),
  Wikidata (23K), Catalogue of Life (12K), SiBBr-published checklists.
- Why: excellent flora coverage lets us measure precision/recall against a large
  ground truth; Brazilian common names are famously many-to-many (one name, many
  species; one species, many names) — good ambiguity-handling test.
- Gold set plan: 300–500 pairs held out from Flora e Funga vernaculars plus
  fisheries common names (many-to-many stress).
- Candidate partner: SiBBr (GBIF node Brazil).

### Tier 2 — scarce-seed flagship (prove the tool creates data that does not exist)

**Pilot 3: Hindi (India), Devanagari + romanized.**
- Script: Devanagari **and** Latin romanizations of the same names ("Mahua" /
  "महुआ" must unify). This is the transliteration and multi-script stress test —
  the scientific novelty of the matching engine.
- Seed reality (measured): Wikidata 124, CoL 8. There is no big open Hindi seed
  list. That is the point. Seeds will be **built**, in this order:
  1. IBP's GBIF-published CC BY data (whatever vernacular fields it carries),
  2. LLM-assisted extraction from openly licensed floras/checklists
     (e.g. government publications confirmed to be open — license check is a
     hard gate per source, done in M1), every extraction human-verified,
  3. the community confirmation loop inside the app itself (every confirmed
     match becomes a new CC0 assertion).
- Gold set plan: 200–300 pairs built with the pilot partner (verified by a
  botanist/zoologist or experienced naturalist), covering trees, birds, fish;
  each entry stored in both Devanagari and at least one romanized spelling.
- Candidate partners: Keystone Foundation, FES (community forest registers),
  IBP/ATREE network. Owner handles outreach — **this is the M6 critical path,
  start early.**

### Deferred (phase 2, not in pilot scope)

- **Swahili**: seeds are even thinner (CoL: 3) and we have no partner lead yet.
  Revisit when a partner materializes; the engine is language-pluggable so adding
  it later is config + seed data, not new code.
- **Chinese**: huge Wikidata coverage (126K) and a real CJK matching challenge,
  but no partner story and CJK fuzzy matching is a research project of its own.

**Why this set wins:** Spanish and Portuguese give judges hard precision/recall
numbers on big gold sets ("quality of implementation"). Hindi gives the story and
the novelty ("innovation", "benefit to the GBIF network") — and the measured
scarcity table above is the opening slide of the video. Three pilots is the most
a solo-maintainer team can carry with honest evaluation for each.

## 4. Constraints from the owner

- **Team:** Abhishek + Claude for now; others join later. Therefore: heavy
  commenting in simple English, modular plug-in/plug-out design, `updatelog.md`
  describing every commit in plain words, onboarding-quality docs.
- **Budget:** free for the initial run; $5–10/month after that if it works.
  Therefore: everything must run in local Docker Compose for development, deploy
  to free tiers for the first public run, and fit one cheap VM (~$5–10, e.g.
  Hetzner/Contabo 2 vCPU/4 GB) for the judged demo. No managed services we
  cannot replace. Details in §10.
- **KB license:** CC0 for our own assertions. CC BY 4.0 source-derived assertions
  keep their attribution in provenance fields (CC BY data can be included in an
  aggregate as long as attribution is preserved — we preserve it per assertion).
- **No commits without explicit ask** (owner's standing rule). `updatelog.md`
  gets an entry every time a commit is made.

## 5. Architecture

### 5.1 Monorepo layout

```
vernabridge/
├── packages/
│   └── namematch/        # Python library: vernacular name -> ranked scientific candidates
├── services/
│   ├── kb/               # Knowledge Base: importers, extraction pipeline, review queue logic
│   └── api/              # FastAPI app: REST API over namematch + KB + jobs
├── apps/
│   └── web/              # SvelteKit app: ingest -> resolve -> complete -> safeguard -> publish
├── data/                 # KB source configs, fixtures, gold sets (NOT the full KB dumps)
├── docs/                 # this file, methods.md, runbook, ADRs (DECISIONS.md)
├── infra/                # docker-compose, deploy scripts, CI config
├── PROGRESS.md           # running status: built / in progress / deferred / known issues
└── updatelog.md          # one plain-English entry per commit
```

Each part is a separate module with its own tests and its own README. The web app
talks to the API only over HTTP; the API imports namematch as a library; namematch
never imports from services. Anything can be unplugged and replaced.

### 5.2 Data flow (the happy path)

```
spreadsheet / photo
      │  upload
      ▼
[apps/web ingest] ──column mapping wizard──► normalized row table
      │  per distinct vernacular name
      ▼
[services/api] ──► [packages/namematch]
      │                 │ lookup + fuzzy + geo-weighting
      │                 ▼
      │           [KB (Postgres)] + [GBIF backbone match, cached]
      ▼
typed result per name: confident | regional_candidates | rank_fallback | unresolved
      │
      ▼
[review UI] human confirms ambiguous names ──► confirmations flow BACK into KB (CC0)
      │
      ▼
[complete] gazetteer + dates + counts
      ▼
[safeguard] sensitive-species screen ──► coordinate generalization (hard gate)
      ▼
[export] Darwin Core Archive (validated) ──► download / IPT push / node handoff
```

### 5.3 Stack decisions (and why)

| Choice | Decision | Why (short) |
|---|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2 | As suggested in brief; boring, typed, well known |
| DB | PostgreSQL 16 + SQLAlchemy 2 + Alembic | One DB for KB + app + audit; full-text and trigram extensions do the fuzzy heavy lifting |
| Job queue | **arq** (Redis-based) | asyncio-native, tiny footprint fits a $5 VM; Celery is heavier than a solo project needs. Recorded as ADR-001 |
| Frontend | **SvelteKit** | Smallest bundles of the mainstream options; the reverse-search page must be <200 KB on 3G Android. ADR-002 |
| Maps | MapLibre GL (with static-image fallback on weak devices) | Open source, no token needed |
| Transliteration | PyICU (ICU transforms) + language-specific rules | ICU is the standard; rules documented per language in methods.md |
| Fuzzy match | Postgres pg_trgm for candidate recall + rapidfuzz re-ranking in Python | Do cheap recall in the DB, precise scoring in code |
| OCR | Tesseract (deva+lat+spa+por packs) first; pluggable interface so a cloud OCR can slot in if quality demands | Free, offline, multi-script; interface keeps us honest about modularity |
| Deploy | Docker Compose everywhere (dev = prod shape) | One-command deploy on any VM |

## 6. Knowledge Base design

### 6.1 Core tables (simplified)

```sql
-- One row = one claim: "this name, in this language, in this region, means this taxon"
kb_assertion (
  id uuid PK,
  vernacular_name text NOT NULL,          -- as written in the source
  name_normalized text NOT NULL,          -- output of our normalization pipeline
  language text NOT NULL,                 -- BCP-47 (e.g. 'hi', 'hi-Latn', 'es-MX')
  script text NOT NULL,                   -- ISO 15924 (e.g. 'Deva', 'Latn')
  region text,                            -- ISO 3166-1/2 (e.g. 'IN', 'IN-MP', 'CO')
  scientific_name text NOT NULL,
  taxon_key bigint NOT NULL,              -- GBIF backbone accepted taxonKey
  backbone_version text NOT NULL,
  source_id uuid FK -> kb_source,
  source_type text NOT NULL,              -- 'checklist' | 'wikidata' | 'extraction' | 'user_confirmation' | 'expert'
  license text NOT NULL,                  -- license of THIS assertion's source
  attribution text,                       -- required when source license is CC BY
  confidence real NOT NULL,               -- source-level prior, 0..1
  verification_status text NOT NULL,      -- 'unverified' | 'verified' | 'disputed' | 'rejected'
  extractor_version text,                 -- set when source_type = 'extraction'
  contributor text,                       -- who confirmed/added (consented display name or anon id)
  created_at timestamptz, superseded_by uuid  -- append-only: corrections create new rows
)

kb_source (id, name, url, license, license_verified_on, access_method, notes)
kb_review (id, assertion_id, reviewer, action, reason, created_at)  -- audit of every status change
kb_release (id, version, zenodo_doi, assertion_count, created_at)
```

Rules:
- Append-only. Nothing is deleted; corrections supersede.
- An assertion contradicting a `verified` one goes to expert-tier review, never
  auto-verified.
- Every release: dump to CSV + Parquet, publish to Zenodo with DOI, and (checked
  in M1) publish as a GBIF checklist dataset using the Vernacular Names extension.
- Our own assertions (confirmations, expert entries): **CC0**. Imported CC BY
  assertions keep `attribution` populated and the release cites every source.

### 6.2 Seed importers for M1 (each one a plug-in module with the same interface)

1. **Wikidata** (CC0) — SPARQL over P1843 + P225, per pilot language.
2. **GBIF checklist vernaculars** — via GBIF API/downloads for the specific CC0/CC BY
   datasets named in §2, provenance per dataset.
3. **CONABIO checklists** (CC0/CC BY) — direct DwC-A downloads.
4. **Flora e Funga do Brasil** (CC BY) — DwC-A vernacular extension.
5. **Catalogue of Life** (CC BY) — ChecklistBank API, filtered to pilot languages.

M1 target: ≥20,000 verified assertions total is realistic for es/pt from these
sources; for Hindi the honest target is **≥500 verified** assertions in M1,
growing via extraction + community loop. We publish the per-language counts —
the imbalance is part of the story, not something to hide.

## 7. namematch pipeline specification

Input: `(raw_name, language_hint?, script_hint?, country?, region?)`
Output: typed result (see below), fully deterministic for a given KB + backbone version.

Stages:

1. **Detect script** from Unicode ranges; language from hint > dataset metadata >
   script-based guess. Never silently guess a language across scripts.
2. **Normalize**: Unicode NFC → script-aware fold (Latin: casefold; Devanagari:
   normalize nukta/anusvara variants, ZWJ/ZWNJ strip) → language-specific
   diacritic policy → generate a **transliteration key** (ISO 15919 for
   Devanagari; identity for Latin) so "महुआ" and "mahua"/"mahuā" share a key.
   Property test: normalization is idempotent.
3. **Candidate recall** against KB, in widening rings (stop early on exact hit):
   exact → normalized-equal → translit-key-equal → trigram similarity ≥ 0.55
   (Latin) / akshara-level edit distance ≤ 2 on translit key (Devanagari — plain
   Levenshtein over code points mis-scores abugidas because one "letter" is a
   consonant+vowel cluster; we compare grapheme clusters). Optional phonetic pass
   (metaphone-style) only for languages where it's linguistically valid — off by
   default, per-language config.
4. **Score** each candidate: string similarity × source confidence ×
   verification bonus × **geographic weight** (assertion region matches record's
   country/region; plus GBIF occurrence density of the candidate taxon in that
   country, cached). One name meaning different species in different places is
   normal and handled here, not an error.
5. **Classify** (defaults, all configurable; justification in methods.md):
   - `confident`: top score ≥ 0.90 AND margin over #2 ≥ 0.15 AND top candidate
     is `verified` — auto-accept allowed but still shown to the user.
   - `regional_candidates`: 2–5 candidates above 0.50 — human must pick.
   - `rank_fallback`: species-level uncertain but candidates share a genus/family
     with combined score ≥ 0.75 — offer genus/family-level record. A conservative
     genus-level record beats a wrong species-level one.
   - `unresolved`: kept in the dataset, never published at species level.
   Nothing below `confident` is ever auto-committed.
6. **Backbone verification**: every surviving candidate goes through GBIF
   species/match (v2, v1 fallback); synonyms resolve to accepted taxonKey;
   matchType + confidence recorded; results cached with backbone version.

Evaluation harness (ships with the library): per-language precision/recall +
coverage against the gold sets in §3, run in CI, numbers published unedited in
`docs/methods.md`. A regression in precision fails the build.

## 8. Publishing app — key design points

(Flow as in the brief; only the decisions worth recording here.)

- **Ingest**: CSV/XLSX parsing server-side with strict validation (size caps,
  formula-injection stripping). Photo → Tesseract OCR → editable grid; OCR is
  behind an interface so a better engine can be plugged in without touching the app.
- **Review UI**: grouped by distinct name; candidate cards show a GBIF/Wikimedia
  image (license checked via API metadata) + mini distribution map + both name
  forms. Tap targets ≥ 48px, works fully without a keyboard, localized in
  es/pt/hi from day one (strings externalized, RTL-ready layout).
- **Safeguard (hard gate in the export layer, tested)**: IUCN category via GBIF
  + CITES appendix list + configurable national lists → coordinate
  generalization; `dataGeneralizations` and `informationWithheld` populated;
  precise coordinates never written into any published artifact.
- **Export**: DwC-A with occurrence core; every row carries `vernacularName` +
  language tag, `verbatimIdentification` (exactly what was written on paper),
  `identificationRemarks` = resolution path (match type, score, who confirmed),
  `taxonKey`, `scientificName`. Golden-file test: fixture spreadsheet in →
  byte-stable archive out. Validate against GBIF's validator API (availability
  re-checked at M3). Publisher of record = the community/institution, never us.
- **Reverse search**: separate ultra-light SvelteKit route, <200 KB initial,
  Web Speech API with text fallback, shareable URLs.

## 9. Competitive review (why nothing existing does this)

| Existing thing | What it does with vernacular names | Why it doesn't solve our problem |
|---|---|---|
| GBIF portal | Displays them; search accepts some | Read-only; coverage is the gap we measured; no publishing path |
| iNaturalist | Localized common names, great ID from photos | Needs a photo per record; can't ingest a name-only spreadsheet/register; names DB is display-oriented |
| taxify (R) `comm2sci` | Offline common→scientific lookup | R library for coders; English-centric sources; no multi-script, no geography, no review flow, no publishing |
| EncicloVida (CONABIO) | Rich Spanish/indigenous name display | Mexico-only, display and search, not a publishing tool |
| India Biodiversity Portal | Common names on species pages | Display; no name-resolution service; no DwC publishing from vernacular input |
| GBIF IPT | The publishing tool | Requires scientificName already resolved; that's exactly the step communities can't do |
| GNames/GNRD, GBIF name parser | Scientific-name matching | Scientific names only |

The gap VernaBridge fills: **resolution engine + human review + Darwin Core
publishing, for any script, packaged for non-technical users** — plus the open
KB, which none of the above produce as a reusable dataset.

## 10. Deployment plan matched to the budget

- **Phase A (free, now → M3)**: local dev via Docker Compose. First shareable
  demo: web app on Vercel/Cloudflare Pages free tier, API + worker on a free
  container tier, Postgres on Supabase/Neon free tier. Known caveat: free
  services sleep and are not demo-safe under judging.
- **Phase B ($5–10/mo, from first end-to-end demo)**: one VM (Hetzner CAX11-class),
  Docker Compose, Caddy for TLS, nightly pg_dump to free object storage. This is
  also the judged-demo shape — judges must never hit a cold-started free dyno.
- Everything is compose-defined so A→B is `docker compose up` on the VM.

## 11. Risks (ranked) and mitigations

1. **Wrong species published to GBIF** (reputation-fatal). Mitigations: threshold
   design in §7, nothing auto-commits below `confident`, genus fallback preferred
   over risky species picks, eval harness gating CI, published error rates.
2. **Partner acquisition slips** (M6 needs 2–3 real datasets published). It's the
   critical path and owned by Abhishek; start outreach during M1, not M5. The
   design keeps a fallback: openly licensed historical registers republished with
   permission count as pilots if a live partner falls through.
3. **Hindi seed cold-start**. Mitigations: extraction pipeline prioritized in M1,
   partner-built gold set, and honest per-language reporting. Worst case, Hindi
   demos the review-heavy path (which is the product's real workflow anyway).
4. **Source licensing mistakes** (self-inflicted disqualification). Mitigation:
   license recorded and verified per source before import (`license_verified_on`),
   IBP scraped-content ban already noted, CC BY attribution carried per assertion.
5. **GBIF API drift (v1↔v2)**. Mitigation: thin client wrapper, recorded
   cassettes in tests, re-verify endpoints at each milestone.
6. **Solo-team scope creep**. Mitigation: milestone gates with explicit
   deferred-lists in PROGRESS.md; phase-2 items (Swahili, Chinese, IPT plugin)
   stay out of pilot scope.
7. **OCR quality on cheap-phone photos**. Mitigation: OCR is assistive, never
   authoritative — the editable grid is the contract; measure OCR accuracy on
   fixture photos and publish it.
8. **Free-tier fragility during judging**. Mitigation: Phase B VM before any
   public demo link is shared.

## 12. What M1 will contain (preview, for approval)

1. Repo scaffolding (monorepo layout, CI with ruff/mypy/pytest, pre-commit,
   `PROGRESS.md`, `updatelog.md`, `DECISIONS.md` with ADR-001/002).
2. KB schema + migrations + the five importers in §6.2 (each pluggable).
3. Provenance + review-queue data model.
4. First KB build: ≥20,000 verified es/pt assertions, ≥500 hi, counts published.
5. Zenodo release pipeline (manual trigger, automated packaging).

## 13. Open questions for the owner (answers unblock M1)

1. **Pilots**: confirm Spanish (CO+MX) + Portuguese (BR) + Hindi (IN), with
   Swahili deferred to phase 2. (Recommended: yes.)
2. **Partners**: can outreach start now for one Indian community-register holder
   (Keystone/FES/ATREE network) and one LatAm node contact? M6 depends on it.
3. **Hindi M1 target**: is ≥500 verified assertions acceptable for M1 (growing
   through M2–M4), given the measured cold-start?
4. **Public repo**: create a GitHub repo now (Apache-2.0) or keep local until M1
   is presentable? Challenge scoring rewards openness — earlier is better.
