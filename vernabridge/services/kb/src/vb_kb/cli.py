"""Command-line entry point for running importers.

Examples (run from services/kb with the venv active):

    python -m vb_kb list
    python -m vb_kb import wikidata --language es --limit 100
    python -m vb_kb import flora-brasil --language pt --out ../../data/samples/pt_flora.jsonl

Importers write JSONL: one assertion per line, ready to be diffed, reviewed,
and later loaded into Postgres (see DECISIONS.md ADR-003).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from vb_kb.importers import REGISTRY
from vb_kb.importers.base import dedupe


def cmd_list() -> int:
    """Show every registered importer, its languages and license."""
    for name, importer_class in REGISTRY.items():
        info = importer_class.source
        langs = ", ".join(importer_class.supported_languages)
        print(f"{name:15s} {info.license:12s} languages: {langs:10s} ({info.name})")
    return 0


def cmd_import(source: str, language: str, limit: int | None, out: Path | None) -> int:
    """Run one importer and write its assertions to a JSONL file."""
    if source not in REGISTRY:
        print(f"Unknown source '{source}'. Known: {', '.join(REGISTRY)}", file=sys.stderr)
        return 2

    importer = REGISTRY[source]()
    if out is None:
        out = Path(f"{source}_{language}.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    with open(out, "w", encoding="utf-8") as handle:
        for assertion in dedupe(importer.iter_assertions(language, limit=limit)):
            handle.write(assertion.model_dump_json() + "\n")
            count += 1
            if count % 500 == 0:
                print(f"  ... {count} assertions so far", file=sys.stderr)

    print(f"Wrote {count} assertions to {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vb_kb", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="show available importers")

    import_parser = subparsers.add_parser("import", help="run one importer")
    import_parser.add_argument("source", help="importer name (see 'list')")
    import_parser.add_argument("--language", required=True, help="BCP-47 tag, e.g. es, pt")
    import_parser.add_argument("--limit", type=int, default=None, help="stop after N assertions")
    import_parser.add_argument("--out", type=Path, default=None, help="output JSONL path")

    args = parser.parse_args(argv)
    if args.command == "list":
        return cmd_list()
    return cmd_import(args.source, args.language, args.limit, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
