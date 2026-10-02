"""Reading the raw HEPData records under data/."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

from . import yamlio


class RawError(ValueError):
    """A HEPData record is missing, ambiguous or not in the expected form."""


_PLACEHOLDERS = {"", "--", "-", "n/a", "na", "nan", "none", "null"}
_INTEGER = re.compile(r"^[+-]?\d+$")


@dataclass(frozen=True)
class Parsed:
    """A number as HEPData wrote it: None for a placeholder, and whether it was a percent."""

    value: int | float | None
    percent: bool = False


def parse_number(raw: Any) -> Parsed:
    """The number in one HEPData cell. Strings such as '1.4e-03' and '5.2%' are read."""
    if raw is None:
        return Parsed(None)
    if isinstance(raw, bool):
        raise RawError(f"{raw!r} is not a number")
    if isinstance(raw, int):
        return Parsed(raw)
    if isinstance(raw, float):
        return Parsed(None) if math.isnan(raw) else Parsed(raw)
    if isinstance(raw, str):
        text = raw.strip()
        if text.lower() in _PLACEHOLDERS:
            return Parsed(None)
        percent = text.endswith("%")
        if percent:
            text = text[:-1].strip()
        try:
            value: int | float = int(text) if _INTEGER.match(text) else float(text)
        except ValueError:
            raise RawError(f"cannot read {raw!r} as a number") from None
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return Parsed(None)
        return Parsed(value, percent)
    raise RawError(f"cannot read {raw!r} as a number")


@dataclass(frozen=True)
class Qualifier:
    name: str
    value: str
    units: str | None = None


@dataclass(frozen=True)
class Variable:
    """One column of a table: a header, its qualifiers (dependent only) and its points."""

    name: str
    units: str | None
    qualifiers: tuple[Qualifier, ...]
    values: tuple[dict[str, Any], ...]

    def qualifier(self, *names: str) -> Qualifier | None:
        wanted = {n.lower() for n in names}
        for qualifier in self.qualifiers:
            if qualifier.name.lower() in wanted:
                return qualifier
        return None


@dataclass(frozen=True)
class TableData:
    independent: tuple[Variable, ...]
    dependent: tuple[Variable, ...]


def _variable(entry: dict[str, Any]) -> Variable:
    header = entry.get("header") or {}
    qualifiers = tuple(
        Qualifier(str(q.get("name", "")), str(q.get("value", "")), q.get("units"))
        for q in entry.get("qualifiers") or []
    )
    return Variable(
        name=str(header.get("name", "")),
        units=header.get("units"),
        qualifiers=qualifiers,
        values=tuple(entry.get("values") or ()),
    )


@dataclass
class Table:
    """A table of a record, as submission.yaml describes it."""

    name: str
    data_file: str
    description: str
    location: str
    doi: str
    directory: Path = field(repr=False, default=Path())

    @cached_property
    def data(self) -> TableData:
        raw = yamlio.load(self.directory / self.data_file)
        return TableData(
            independent=tuple(_variable(v) for v in raw.get("independent_variables") or ()),
            dependent=tuple(_variable(v) for v in raw.get("dependent_variables") or ()),
        )


@dataclass
class RawRecord:
    path: Path
    inspire_id: int
    version: int
    doi: str
    comment: str
    tables: dict[str, Table]

    def table(self, name: str) -> Table:
        try:
            return self.tables[name]
        except KeyError:
            known = ", ".join(list(self.tables)[:6]) + (" ..." if len(self.tables) > 6 else "")
            raise RawError(
                f"ins{self.inspire_id} v{self.version} has no table {name!r} (it has {known})"
            ) from None


_DIRECTORY = re.compile(r"^HEPData-ins(\d+)-v(\d+)-yaml$")


def _digest(directory: Path) -> str:
    sha = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        sha.update(str(path.relative_to(directory)).encode())
        sha.update(path.read_bytes())
    return sha.hexdigest()


def find_record_directory(root: str | Path, inspire_id: int, version: int) -> Path:
    """The unpacked record under data/. Copies of one record must be identical."""
    name = f"HEPData-ins{inspire_id}-v{version}-yaml"
    matches = sorted(p for p in (Path(root) / "data").glob(f"**/{name}") if p.is_dir())
    if not matches:
        raise RawError(
            f"ins{inspire_id} v{version} is not under data/: unpack HEPData-ins{inspire_id}-"
            f"v{version}-yaml there (hsdc fetch does this)"
        )
    first = _digest(matches[0])
    for other in matches[1:]:
        if _digest(other) != first:
            raise RawError(f"the copies of ins{inspire_id} v{version} differ: {matches[0]}, {other}")
    return matches[0]


def load_record(directory: str | Path) -> RawRecord:
    directory = Path(directory)
    match = _DIRECTORY.match(directory.name)
    if not match:
        raise RawError(f"{directory} is not named HEPData-ins<id>-v<version>-yaml")
    documents = yamlio.load_all(directory / "submission.yaml")
    head, entries = documents[0] or {}, documents[1:]
    tables: dict[str, Table] = {}
    for entry in entries:
        name = str(entry["name"])
        if name in tables:
            raise RawError(f"{directory.name}: two tables are named {name!r}")
        tables[name] = Table(
            name=name,
            data_file=str(entry["data_file"]),
            description=str(entry.get("description") or ""),
            location=str(entry.get("location") or ""),
            doi=str(entry.get("table_doi") or ""),
            directory=directory,
        )
    return RawRecord(
        path=directory,
        inspire_id=int(match.group(1)),
        version=int(match.group(2)),
        doi=str(head.get("hepdata_doi") or ""),
        comment=str(head.get("comment") or ""),
        tables=tables,
    )


def open_record(root: str | Path, inspire_id: int, version: int) -> RawRecord:
    return load_record(find_record_directory(root, inspire_id, version))
