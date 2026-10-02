"""Reading curated datasets.

    from hsdc import read_datasets, tidy, tidy_errors

    datasets = read_datasets(observable="raa", system="PbPb", sqrt_s_nn=5020)
    points = tidy(datasets)          # one row per bin
    sources = tidy_errors(datasets)  # one row per bin and error source

Errors are returned as published: a number is a symmetric error and [minus, plus] an
asymmetric one, with their signs. What to do with them is the caller's decision.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from . import yamlio

FORMAT_VERSION = 1
_RANGE_FIELDS = ("centrality", "reference_centrality", "eta_range", "y_range", "pt_range")


class FormatError(ValueError):
    """A dataset file is not of a format this reader understands."""


@dataclass(frozen=True)
class Bin:
    value: float | None
    low: float | None = None
    high: float | None = None
    centre: float | None = None
    errors: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Dataset:
    """One curve: one observable, one class, one selection."""

    key: str
    observable: str
    system: str
    sqrt_s_nn: float
    experiment: str
    particle: str
    source: dict[str, Any]
    x: dict[str, Any]
    y: dict[str, Any]
    errors: dict[str, dict[str, Any]]
    bins: tuple[Bin, ...]
    centrality: tuple[float, float] | None = None
    centrality_definition: str | None = None
    reference_centrality: tuple[float, float] | None = None
    acceptance: dict[str, Any] = field(default_factory=dict)
    # harmonic, method and any other field the observable registry defines.
    extra: dict[str, Any] = field(default_factory=dict)
    note: str | None = None
    path: Path | None = None
    # The file as loaded, for the registry's lookups.
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def get(self, name: str, default: Any = None) -> Any:
        """A field by name, wherever it lives: the top level, `y` or `acceptance`."""
        if name in self.__dataclass_fields__ and name not in ("extra", "path", "raw"):
            return getattr(self, name)
        for place in (self.extra, self.y, self.acceptance):
            if name in place:
                return place[name]
        return default

    @property
    def has_edges(self) -> bool:
        return bool(self.bins) and self.bins[0].low is not None

    @property
    def edges(self) -> list[tuple[Any, Any]]:
        """[(low, high)] per bin; empty for a dataset with centres only."""
        return [(b.low, b.high) for b in self.bins] if self.has_edges else []

    @property
    def centres(self) -> list[float | None]:
        return [b.centre for b in self.bins]


def find_root(start: str | Path | None = None) -> Path:
    """The data repository: ``start`` or a parent of it, else $HSDC_ROOT, else this checkout."""
    candidates: list[Path] = []
    if start is not None:
        here = Path(start).resolve()
        candidates.extend([here, *here.parents])
    if os.environ.get("HSDC_ROOT"):
        candidates.append(Path(os.environ["HSDC_ROOT"]))
    candidates.append(Path(__file__).resolve().parents[2])
    here = Path.cwd().resolve()
    candidates.extend([here, *here.parents])
    for path in candidates:
        if (path / "observables.yaml").exists():
            return path
    raise FileNotFoundError(
        "cannot find the data repository (no observables.yaml): pass its path or set HSDC_ROOT"
    )


def _pair(value: Any) -> tuple[float, float] | None:
    return None if value is None else (value[0], value[1])


def dataset_from_dict(raw: dict[str, Any], path: Path | None = None) -> Dataset:
    version = raw.get("format_version")
    if version != FORMAT_VERSION:
        raise FormatError(
            f"{path or 'dataset'}: format_version {version!r}, this reader reads {FORMAT_VERSION}"
        )
    known = {
        "format_version", "key", "observable", "system", "sqrt_s_nn", "experiment", "particle",
        "source", "x", "y", "errors", "bins", "centrality", "centrality_definition",
        "reference_centrality", "acceptance", "note",
    }  # fmt: skip
    return Dataset(
        key=raw["key"],
        observable=raw["observable"],
        system=raw["system"],
        sqrt_s_nn=raw["sqrt_s_nn"],
        experiment=raw["experiment"],
        particle=raw["particle"],
        source=raw["source"],
        x=raw["x"],
        y=raw["y"],
        errors=raw["errors"],
        bins=tuple(
            Bin(
                value=b["value"],
                low=b.get("low"),
                high=b.get("high"),
                centre=b.get("centre"),
                errors=b.get("errors", {}),
            )
            for b in raw["bins"]
        ),
        centrality=_pair(raw.get("centrality")),
        centrality_definition=raw.get("centrality_definition"),
        reference_centrality=_pair(raw.get("reference_centrality")),
        acceptance=raw.get("acceptance", {}),
        extra={k: v for k, v in raw.items() if k not in known},
        note=raw.get("note"),
        path=path,
        raw=raw,
    )


def read_dataset(path: str | Path) -> Dataset:
    path = Path(path)
    return dataset_from_dict(yamlio.load(path), path)


@lru_cache(maxsize=4)
def _registry(root: str):
    from . import registry

    return registry.load(root)


def final_kind(dataset: Dataset, root: str | Path | None = None) -> str | None:
    """The CapeTownEloss final observable that computes the dataset, or None if the model
    cannot (a method or spectrum definition the registry gives no final for)."""
    from . import registry

    registry_ = _registry(str(find_root() if root is None else Path(root)))
    return registry.final_kind(registry_.observables[dataset.observable], dataset.raw, registry_)


def dataset_files(root: str | Path, *, curated: bool = True, manual: bool = True) -> list[Path]:
    root = Path(root)
    folders = (["curated"] if curated else []) + (["manual"] if manual else [])
    files: list[Path] = []
    for folder in folders:
        files.extend((root / folder).rglob("*.yaml"))
    return sorted(files)


def _matches(dataset: Dataset, name: str, wanted: Any) -> bool:
    have = dataset.get(name)
    if name in _RANGE_FIELDS:
        options = wanted if wanted and isinstance(wanted[0], (list, tuple)) else [wanted]
        return have is not None and any(tuple(have) == tuple(o) for o in options)
    if isinstance(wanted, (list, tuple, set, frozenset)):
        return have in wanted
    return have == wanted


def read_datasets(
    root: str | Path | None = None,
    *,
    curated: bool = True,
    manual: bool = True,
    **filters: Any,
) -> list[Dataset]:
    """Every dataset whose fields match the filters, sorted by key.

    A filter is a field name and a value, or a list of values for "any of". Ranges such
    as ``centrality=[0, 5]`` are compared as pairs.
    """
    root = find_root() if root is None else Path(root)
    found = []
    for path in dataset_files(root, curated=curated, manual=manual):
        dataset = read_dataset(path)
        if all(_matches(dataset, n, v) for n, v in filters.items()):
            found.append(dataset)
    return sorted(found, key=lambda d: d.key)


def _frame(rows: list[dict[str, Any]]) -> Any:
    import pandas as pd

    return pd.DataFrame(rows)


def _identity(dataset: Dataset) -> dict[str, Any]:
    row: dict[str, Any] = {
        "key": dataset.key,
        "observable": dataset.observable,
        "system": dataset.system,
        "sqrt_s_nn": dataset.sqrt_s_nn,
        "experiment": dataset.experiment,
        "particle": dataset.particle,
        "centrality_lo": dataset.centrality[0] if dataset.centrality else None,
        "centrality_hi": dataset.centrality[1] if dataset.centrality else None,
        "centrality_definition": dataset.centrality_definition,
    }
    for name, value in dataset.extra.items():
        row[name] = value
    if "definition" in dataset.y:
        row["definition"] = dataset.y["definition"]
    return row


def tidy(datasets: Iterable[Dataset]) -> Any:
    """One row per bin: the dataset's identity, the bin's position and its value."""
    rows = []
    for dataset in datasets:
        identity = _identity(dataset)
        for index, b in enumerate(dataset.bins):
            rows.append({**identity, "bin": index, "low": b.low, "high": b.high,
                         "centre": b.centre, "value": b.value})  # fmt: skip
    return _frame(rows)


def tidy_errors(datasets: Iterable[Dataset]) -> Any:
    """One row per bin and error source, as published.

    ``symmetric`` is set for a source given as one number, ``minus`` and ``plus`` for one
    given as a pair; the other columns are empty. ``origin`` is the table's label or where
    a typed-in value came from.
    """
    rows = []
    for dataset in datasets:
        for index, b in enumerate(dataset.bins):
            for name, value in b.errors.items():
                definition = dataset.errors[name]
                pair = isinstance(value, list)
                rows.append({
                    "key": dataset.key,
                    "bin": index,
                    "source": name,
                    "symmetric": None if pair else value,
                    "minus": value[0] if pair else None,
                    "plus": value[1] if pair else None,
                    "origin": definition.get("origin", "table"),
                    "label": definition.get("label"),
                    "percent": bool(definition.get("percent", False)),
                })  # fmt: skip
    return _frame(rows)
