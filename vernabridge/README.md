# VernaBridge

Publish biodiversity data recorded in local languages to GBIF via Darwin Core.

Vast amounts of biodiversity data are written using vernacular (local-language)
species names and never reach GBIF, because nothing bridges those names to
scientific names reliably enough to publish. VernaBridge is that missing on-ramp.

Built for the 2027 GBIF Ebbe Nielsen Challenge. Read [docs/design.md](docs/design.md)
for the full design, [PROGRESS.md](PROGRESS.md) for status, and
[updatelog.md](updatelog.md) for a plain-English history of every commit.

## Current pilots

1. **Spanish** (Colombia + Mexico) — rich open seed data
2. **Portuguese** (Brazil) — rich open seed data
3. **Hindi** (India) — starts only after Spanish + Portuguese are fully verified

## Repository layout

```
vernabridge/
├── docs/           # design doc, methods, decisions
├── services/kb/    # Knowledge Base: seed-data importers (start here)
├── packages/       # namematch library (arrives in M2)
├── apps/           # web app (arrives in M3)
└── data/           # small samples and fixtures only — never full dumps
```

## Quickstart (importers)

```bash
cd services/kb
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                                   # offline tests
python -m vb_kb import wikidata --language es --limit 100   # live sample pull
```

## Principles

- Simple-English comments everywhere; new contributors should never be lost.
- Every module is pluggable: importers share one interface, and can be added
  or removed without touching anything else.
- Every piece of data carries its source and license (provenance is sacred).
- No personal data in outbound requests; clients identify as
  `VernaBridge/x.y (+https://github.com/thesamotar/GB_Submission)`.

## Licenses

Code: Apache-2.0 (to confirm at first release). Knowledge Base: CC0 for our own
assertions; imported CC BY data keeps its attribution. Docs: CC BY 4.0.
