"""VernaBridge Knowledge Base tools.

This package pulls vernacular (local-language) species names from open data
sources and turns them into "assertions" — small, well-described claims like:
"the name 'sabiá' in Portuguese, in Brazil, refers to Turdus rufiventris".

Everything here is deliberately simple and pluggable:
- one importer per source, all sharing the same interface (see importers/base.py)
- importers write JSONL files, not database rows (see DECISIONS.md, ADR-003)
- every assertion carries its source and license (provenance is sacred)
"""

__version__ = "0.1.0"
