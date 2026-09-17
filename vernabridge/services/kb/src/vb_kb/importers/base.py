"""The interface every seed-data importer must follow.

An importer's whole job: talk to one open data source and yield Assertion
objects. It must NOT write files, touch databases, or know about other
importers. That keeps each one small, testable, and replaceable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator

from vb_kb.models import Assertion, SourceInfo


class BaseImporter(ABC):
    """Extend this class to add a new data source.

    Subclasses must:
    - set `source` (the fixed facts about the source: name, license, ...)
    - set `supported_languages` (BCP-47 tags this importer can serve)
    - implement `iter_assertions()`
    """

    source: SourceInfo
    supported_languages: tuple[str, ...]

    def check_language(self, language: str) -> None:
        """Fail loudly when asked for a language this source can't provide."""
        if language not in self.supported_languages:
            raise ValueError(
                f"{self.source.name} supports {self.supported_languages}, not '{language}'"
            )

    @abstractmethod
    def iter_assertions(self, language: str, limit: int | None = None) -> Iterator[Assertion]:
        """Yield assertions for one language, up to `limit` (None = everything).

        Implementations should yield as they go (streaming), never build the
        whole list in memory — some sources have hundreds of thousands of rows.
        """
        ...


def dedupe(assertions: Iterator[Assertion]) -> Iterator[Assertion]:
    """Drop repeated claims within one run (same name+language+taxon+region).

    Sources often list the same name twice (e.g. once per reference).
    Keeps the first occurrence, which also keeps output order stable.
    """
    seen: set[tuple[str, str, str, str | None]] = set()
    for assertion in assertions:
        key = assertion.dedupe_key()
        if key in seen:
            continue
        seen.add(key)
        yield assertion
