"""Generic Darwin Core Archive (DwC-A) reading.

A DwC-A is a zip file: `meta.xml` describes which text files are inside and
what each column means. This module knows how to read the VernacularName
extension out of any such archive and join it to the taxon core.

No importer uses this right now (our current archive sources are reachable
through the ChecklistBank API instead), but it is tested and ready for open
checklists that are published only as DwC-A files.
"""

from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

# Darwin Core term URIs we care about (the tail after the last '/' is enough).
TERM_SCIENTIFIC_NAME = "scientificName"
TERM_VERNACULAR_NAME = "vernacularName"
TERM_LANGUAGE = "language"
ROWTYPE_VERNACULAR = "http://rs.gbif.org/terms/1.0/VernacularName"


@dataclass
class FileSpec:
    """Where one data file lives inside the archive and what its columns mean."""

    location: str  # file name inside the zip
    delimiter: str  # column separator, usually tab or comma
    encoding: str
    skip_lines: int  # header lines to ignore
    id_index: int  # column holding the record id / core id
    columns: dict[str, int]  # DwC term (short form) -> column index


def parse_meta_xml(meta_bytes: bytes) -> tuple[FileSpec, FileSpec | None]:
    """Read meta.xml and return (taxon core spec, vernacular extension spec).

    Returns None for the extension when the archive has no vernacular names —
    callers should treat that as 'this source has nothing for us', not an error.
    """
    # meta.xml uses a default namespace; strip it so tag names stay readable.
    root = ET.fromstring(meta_bytes)
    namespace = root.tag.split("}")[0] + "}" if "}" in root.tag else ""

    def build_spec(node: ET.Element, id_tag: str) -> FileSpec:
        location_node = node.find(f"{namespace}files/{namespace}location")
        if location_node is None or location_node.text is None:
            raise ValueError("meta.xml file entry has no location")
        id_node = node.find(f"{namespace}{id_tag}")
        columns: dict[str, int] = {}
        for field in node.findall(f"{namespace}field"):
            term = field.get("term", "")
            index = field.get("index")
            if index is not None:
                columns[term.rsplit("/", 1)[-1]] = int(index)
        # Delimiters arrive as escaped text like "\t" — decode them.
        delimiter = (node.get("fieldsTerminatedBy") or ",").encode().decode("unicode_escape")
        return FileSpec(
            location=location_node.text.strip(),
            delimiter=delimiter or ",",
            encoding=node.get("encoding") or "utf-8",
            skip_lines=int(node.get("ignoreHeaderLines") or 0),
            id_index=int(id_node.get("index") or 0) if id_node is not None else 0,
            columns=columns,
        )

    core_node = root.find(f"{namespace}core")
    if core_node is None:
        raise ValueError("meta.xml has no core element — not a valid DwC archive")
    core = build_spec(core_node, "id")

    extension: FileSpec | None = None
    for ext_node in root.findall(f"{namespace}extension"):
        if ext_node.get("rowType") == ROWTYPE_VERNACULAR:
            extension = build_spec(ext_node, "coreid")
            break
    return core, extension


class DwcaVernacularReader:
    """Reads (vernacular name, language, scientific name) rows from a DwC archive zip."""

    def __init__(self, archive_path: Path):
        self.archive_path = archive_path

    def iter_rows(self) -> Iterator[tuple[str, str, str]]:
        """Yield (vernacular_name, raw_language, scientific_name) tuples."""
        with zipfile.ZipFile(self.archive_path) as archive:
            core, extension = parse_meta_xml(archive.read("meta.xml"))
            if extension is None:
                return  # this archive simply has no vernacular names

            # Pass 1: build id -> scientific name from the taxon core.
            # The core can be large (168k rows for Flora e Funga) but a dict of
            # short strings fits comfortably in memory on any machine we target.
            sci_index = core.columns.get(TERM_SCIENTIFIC_NAME)
            if sci_index is None:
                return
            id_to_name: dict[str, str] = {}
            for row in self._read_csv(archive, core):
                if len(row) > max(core.id_index, sci_index) and row[sci_index]:
                    id_to_name[row[core.id_index]] = row[sci_index]

            # Pass 2: walk the vernacular extension and join on the core id.
            name_index = extension.columns.get(TERM_VERNACULAR_NAME)
            lang_index = extension.columns.get(TERM_LANGUAGE)
            if name_index is None:
                return
            for row in self._read_csv(archive, extension):
                if len(row) <= name_index or not row[name_index]:
                    continue
                scientific = id_to_name.get(row[extension.id_index])
                if not scientific:
                    continue  # orphan row; nothing to anchor it to
                raw_language = (
                    row[lang_index] if lang_index is not None and len(row) > lang_index else ""
                )
                yield row[name_index], raw_language, scientific

    def _read_csv(self, archive: zipfile.ZipFile, spec: FileSpec) -> Iterator[list[str]]:
        """Stream one file out of the zip as rows of strings."""
        with archive.open(spec.location) as raw:
            text = io.TextIOWrapper(raw, encoding=spec.encoding, errors="replace")
            reader = csv.reader(text, delimiter=spec.delimiter)
            for line_number, row in enumerate(reader):
                if line_number < spec.skip_lines:
                    continue
                yield row
