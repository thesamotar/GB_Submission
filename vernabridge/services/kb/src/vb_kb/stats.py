"""KB statistics: what is in the Knowledge Base right now?

Answers the questions we keep asking ourselves (and that PROGRESS.md and the
Challenge entry need numbers for): how many assertions per language, from
which sources, how many are anchored to the GBIF backbone, how many verified.

Works on both stages of the pipeline:
- JSONL files (before loading) — `python -m vb_kb stats file1.jsonl ...`
- the database (after loading) — `python -m vb_kb stats --dsn ...`

There is deliberately NO web frontend for this in M1: a table in the
terminal serves the solo team fine, and the real reporting surface arrives
with the API service (M2) and web app (M3). See docs/design.md section 5.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from vb_kb.models import Assertion


@dataclass
class KbStats:
    """Counts describing one snapshot of the KB (files or database)."""

    total: int = 0
    by_language: Counter[str] = field(default_factory=Counter)
    by_source: Counter[str] = field(default_factory=Counter)
    by_status: Counter[str] = field(default_factory=Counter)
    anchored: int = 0  # taxon_key present

    def add(
        self, language: str, source_name: str, status: str, has_taxon_key: bool, count: int = 1
    ) -> None:
        """Fold `count` rows with these properties into the totals."""
        self.total += count
        self.by_language[language] += count
        self.by_source[source_name] += count
        self.by_status[status] += count
        if has_taxon_key:
            self.anchored += count

    def render(self) -> str:
        """Human-readable table for the terminal. Kept plain on purpose."""
        lines = [f"Total assertions: {self.total}"]
        if self.total == 0:
            return lines[0]
        pct = 100.0 * self.anchored / self.total
        lines.append(f"Anchored to GBIF backbone (taxon_key set): {self.anchored} ({pct:.1f}%)")
        lines.append("")
        lines.append("By language:")
        for language, count in self.by_language.most_common():
            lines.append(f"  {language:10s} {count:>8d}")
        lines.append("By source:")
        for source, count in self.by_source.most_common():
            lines.append(f"  {source:40s} {count:>8d}")
        lines.append("By verification status:")
        for status, count in self.by_status.most_common():
            lines.append(f"  {status:12s} {count:>8d}")
        return "\n".join(lines)


def stats_from_files(paths: list[Path]) -> KbStats:
    """Count assertions across JSONL files (pre-database stage)."""
    stats = KbStats()
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                assertion = Assertion.model_validate(json.loads(line))
                stats.add(
                    language=assertion.language,
                    source_name=assertion.source_name,
                    status=assertion.verification_status.value,
                    has_taxon_key=assertion.taxon_key is not None,
                )
    return stats


def stats_from_db(session: Session) -> KbStats:
    """Count assertions in the database with GROUP BY (never row-by-row)."""
    # Imported here so the JSONL path works even if db extras are missing.
    from vb_kb.db import KbAssertion, KbSource

    stats = KbStats()
    rows = session.execute(
        select(
            KbAssertion.language,
            KbSource.name,
            KbAssertion.verification_status,
            KbAssertion.taxon_key.is_not(None),
            func.count(),
        )
        .join(KbSource, KbAssertion.source_id == KbSource.id)
        .group_by(
            KbAssertion.language,
            KbSource.name,
            KbAssertion.verification_status,
            KbAssertion.taxon_key.is_not(None),
        )
    ).all()
    for language, source_name, status, has_key, count in rows:
        stats.add(
            language=language,
            source_name=source_name,
            status=status,
            has_taxon_key=bool(has_key),
            count=int(count),
        )
    return stats
