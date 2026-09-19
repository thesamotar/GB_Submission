"""Command-line entry point for running importers.

The pipeline, in order (each step is one command, per DECISIONS.md ADR-003):

    python -m vb_kb list
    python -m vb_kb import wikidata --language es --out es_wikidata.jsonl
    python -m vb_kb resolve es_wikidata.jsonl --out es_resolved.jsonl
    python -m vb_kb load es_resolved.jsonl --dsn postgresql+psycopg://...
    python -m vb_kb stats es_resolved.jsonl        # or: stats --dsn ...

The database DSN can also come from the VB_DB_DSN environment variable so
scripts don't have to repeat it (and passwords stay out of shell history).
"""

from __future__ import annotations

import argparse
import os
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


def cmd_resolve(in_path: Path, out: Path | None, cache: Path) -> int:
    """Run the backbone-resolve step over one JSONL file."""
    import json
    from collections.abc import Iterator

    from vb_kb.backbone import BackboneResolver, ResolveReport, resolve_assertions
    from vb_kb.models import Assertion

    if out is None:
        out = in_path.with_name(in_path.stem + "_resolved.jsonl")
    resolver = BackboneResolver(cache_path=cache)
    report = ResolveReport()

    def read_assertions() -> Iterator[Assertion]:
        with open(in_path, encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield Assertion.model_validate(json.loads(line))

    try:
        with open(out, "w", encoding="utf-8") as sink:
            for assertion in resolve_assertions(read_assertions(), resolver, report):
                sink.write(assertion.model_dump_json() + "\n")
                if report.total % 500 == 0:
                    print(f"  ... {report.total} rows processed", file=sys.stderr)
    finally:
        resolver.save_cache()  # keep what we learned even if the run dies midway

    print(
        f"Resolved {in_path} -> {out}: {report.total} rows, "
        f"{report.already_anchored} already anchored, {report.anchored_now} anchored now, "
        f"{report.left_unresolved} left for review ({report.higher_rank} of them matched "
        f"above species rank) ({report.api_calls} API calls, cache: {cache})"
    )
    return 0


def _dsn_or_fail(dsn: str | None) -> str:
    """Resolve the database DSN from the flag or VB_DB_DSN, or exit loudly."""
    resolved = dsn or os.environ.get("VB_DB_DSN")
    if not resolved:
        print("No database DSN. Pass --dsn or set VB_DB_DSN.", file=sys.stderr)
        raise SystemExit(2)
    return resolved


def cmd_load(paths: list[Path], dsn: str | None) -> int:
    """Load JSONL files into the database, idempotently."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from vb_kb.db import LoadReport, load_jsonl

    engine = create_engine(_dsn_or_fail(dsn))
    report = LoadReport()
    with Session(engine) as session:
        for path in paths:
            load_jsonl(session, path, report)
        session.commit()
    print(
        f"Loaded {len(report.files)} file(s): {report.read} rows read, "
        f"{report.inserted} inserted, {report.skipped_existing} already present, "
        f"{report.sources_created} source(s) created"
    )
    return 0


def cmd_stats(paths: list[Path], dsn: str | None) -> int:
    """Show what is in the KB — from JSONL files or from the database."""
    from vb_kb.stats import stats_from_db, stats_from_files

    if paths:
        print(stats_from_files(paths).render())
        return 0
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine(_dsn_or_fail(dsn))
    with Session(engine) as session:
        print(stats_from_db(session).render())
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

    resolve_parser = subparsers.add_parser(
        "resolve", help="fill GBIF taxonKeys for a JSONL file (backbone-resolve step)"
    )
    resolve_parser.add_argument("input", type=Path, help="JSONL file from an importer")
    resolve_parser.add_argument("--out", type=Path, default=None, help="output JSONL path")
    resolve_parser.add_argument(
        "--cache",
        type=Path,
        default=Path("backbone_cache.json"),
        help="on-disk cache of GBIF answers, shared across runs",
    )

    load_parser = subparsers.add_parser("load", help="load JSONL files into the database")
    load_parser.add_argument("inputs", type=Path, nargs="+", help="JSONL files to load")
    load_parser.add_argument("--dsn", default=None, help="database DSN (or set VB_DB_DSN)")

    stats_parser = subparsers.add_parser(
        "stats", help="show KB counts (from JSONL files, or from the database with --dsn)"
    )
    stats_parser.add_argument("inputs", type=Path, nargs="*", help="JSONL files to count")
    stats_parser.add_argument("--dsn", default=None, help="database DSN (or set VB_DB_DSN)")

    args = parser.parse_args(argv)
    if args.command == "list":
        return cmd_list()
    if args.command == "import":
        return cmd_import(args.source, args.language, args.limit, args.out)
    if args.command == "resolve":
        return cmd_resolve(args.input, args.out, args.cache)
    if args.command == "load":
        return cmd_load(args.inputs, args.dsn)
    return cmd_stats(args.inputs, args.dsn)


if __name__ == "__main__":
    raise SystemExit(main())
