"""Recipes: the one place a curator's judgement is written down, one file per record."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import yamlio
from .registry import ERROR_ORIGINS


class RecipeError(ValueError):
    """A recipe is malformed."""


# Dataset fields that every observable has. The others -- centrality, harmonic, method, variant,
# definition and so on -- are the registry's `fields`, so that a field added there is allowed in a
# recipe without touching this file.
BASE_FIELDS = (
    "observable",
    "system",
    "sqrt_s_nn",
    "experiment",
    "particle",
    "acceptance",
    "note",
    "figure",
)
_ENTRY_ONLY = ("table", "column", "x_index")
_RECIPE_KEYS = {"record", "paper", "datasets", "errors", "additional", "known_warnings"}
_ERROR_KEYS = {"label", "note"}
_ADDITIONAL_KEYS = {
    "origin", "reference", "entered_by", "for", "sample", "relative", "values", "note"
}  # fmt: skip


@dataclass
class DatasetSpec:
    table: str
    column: int
    x_index: int | None
    fields: dict[str, Any]
    index: int = 0


@dataclass
class Additional:
    name: str
    origin: str
    reference: str | None
    entered_by: str | None
    selector: dict[str, Any]
    sample: str | None
    relative: Any
    values: dict[str, list[Any]] | None
    note: str | None


@dataclass
class Recipe:
    path: Path
    inspire_id: int
    version: int
    paper: str | None
    datasets: list[DatasetSpec]
    errors: dict[str, dict[str, Any]] = field(default_factory=dict)
    additional: list[Additional] = field(default_factory=list)
    # Text of warnings this recipe has explained, in a comment, as a quirk of the record.
    known_warnings: list[str] = field(default_factory=list)


def _fail(path: Path, message: str) -> RecipeError:
    return RecipeError(f"{path.name}: {message}")


def _text_keys(path: Path, mapping: Any, where: str) -> None:
    """YAML reads a bare on, off, yes or no as a boolean, so such a key is not text."""
    if isinstance(mapping, dict):
        for key in mapping:
            if not isinstance(key, str):
                raise _fail(
                    path,
                    f"{where}: the key {key!r} is not text (YAML reads on, off, yes and no as "
                    f"booleans, and 1 as a number): put it in quotes",
                )


def _additional(path: Path, name: str, entry: Any) -> Additional:
    if not isinstance(entry, dict):
        raise _fail(path, f"additional.{name} must be a mapping")
    _text_keys(path, entry, f"additional.{name}")
    unknown = set(entry) - _ADDITIONAL_KEYS
    if unknown:
        raise _fail(path, f"additional.{name}: unknown keys {sorted(unknown)}")
    origin = entry.get("origin")
    if origin not in ERROR_ORIGINS:
        raise _fail(path, f"additional.{name}.origin must be one of {list(ERROR_ORIGINS)}")
    if origin == "paper" and not entry.get("reference"):
        raise _fail(path, f"additional.{name}: origin 'paper' needs a 'reference' (section, table)")
    if origin == "manual" and not entry.get("entered_by"):
        raise _fail(path, f"additional.{name}: origin 'manual' needs 'entered_by'")
    if ("relative" in entry) == ("values" in entry):
        raise _fail(path, f"additional.{name} needs exactly one of 'relative' and 'values'")
    values = entry.get("values")
    if values is not None and not (
        isinstance(values, dict) and all(isinstance(v, list) for v in values.values())
    ):
        raise _fail(path, f"additional.{name}.values must map a class to a list, one per bin")
    return Additional(
        name=name,
        origin=origin,
        reference=entry.get("reference"),
        entered_by=entry.get("entered_by"),
        selector=dict(entry.get("for") or {}),
        sample=entry.get("sample"),
        relative=entry.get("relative"),
        values=values,
        note=entry.get("note"),
    )


def load_recipe(path: str | Path, dataset_fields: Iterable[str] | None = None) -> Recipe:
    """Read a recipe. ``dataset_fields`` are the field names a dataset may set (BASE_FIELDS plus
    the registry's); without them only the record is read, as the update commands need."""
    path = Path(path)
    allowed = None if dataset_fields is None else set(BASE_FIELDS) | set(dataset_fields)
    raw = yamlio.load(path)
    if not isinstance(raw, dict):
        raise _fail(path, "must be a mapping")
    _text_keys(path, raw, "top level")
    unknown = set(raw) - _RECIPE_KEYS - (allowed or set(raw))
    if unknown:
        raise _fail(path, f"unknown keys {sorted(unknown)}")
    record = raw.get("record") or {}
    if set(record) != {"inspire_id", "version"}:
        raise _fail(path, "record must be { inspire_id: <int>, version: <int> }")
    defaults = {k: v for k, v in raw.items() if k not in _RECIPE_KEYS}

    entries = raw.get("datasets")
    if not isinstance(entries, list) or not entries:
        raise _fail(path, "datasets must be a non-empty list")
    datasets = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or "table" not in entry:
            raise _fail(path, f"datasets[{index}] must be a mapping with a 'table'")
        _text_keys(path, entry, f"datasets[{index}]")
        unknown = set(entry) - set(_ENTRY_ONLY) - (allowed if allowed is not None else set(entry))
        if unknown:
            raise _fail(path, f"datasets[{index}] ({entry['table']}): unknown keys {sorted(unknown)}")
        merged = dict(defaults)
        for key in entry:
            if key in _ENTRY_ONLY:
                continue
            if key == "acceptance" and isinstance(defaults.get("acceptance"), dict):
                merged["acceptance"] = {**defaults["acceptance"], **entry["acceptance"]}
            else:
                merged[key] = entry[key]
        datasets.append(
            DatasetSpec(
                table=str(entry["table"]),
                column=int(entry.get("column", 0)),
                x_index=entry.get("x_index"),
                fields=merged,
                index=index,
            )
        )

    errors = raw.get("errors") or {}
    for name, entry in errors.items():
        if not isinstance(entry, dict) or set(entry) - _ERROR_KEYS:
            raise _fail(path, f"errors.{name} may only have {sorted(_ERROR_KEYS)}")

    additional = []
    for name, entry in (raw.get("additional") or {}).items():
        # One name can be given several entries, each with its own `for:`.
        for item in entry if isinstance(entry, list) else [entry]:
            additional.append(_additional(path, str(name), item))
    return Recipe(
        path=path,
        inspire_id=int(record["inspire_id"]),
        version=int(record["version"]),
        paper=raw.get("paper"),
        datasets=datasets,
        errors={str(k): dict(v) for k, v in errors.items()},
        additional=additional,
        known_warnings=[str(w) for w in raw.get("known_warnings") or []],
    )
