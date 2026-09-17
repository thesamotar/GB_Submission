"""Importer registry.

Every importer registers itself here under a short name. The CLI (and later
the scheduled jobs) look importers up by that name. To add a new source:
write a module with a class extending BaseImporter, and add one line below.
To remove a source: delete its line. Nothing else changes — that is the
"plug and unplug" promise of this codebase.
"""

from __future__ import annotations

from vb_kb.importers.base import BaseImporter
from vb_kb.importers.checklistbank import CatalogueOfLifeImporter, FloraBrasilImporter
from vb_kb.importers.wikidata import WikidataImporter

REGISTRY: dict[str, type[BaseImporter]] = {
    "wikidata": WikidataImporter,
    "col": CatalogueOfLifeImporter,
    "flora-brasil": FloraBrasilImporter,
}
