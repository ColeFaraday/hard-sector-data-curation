"""What a dataset may say: the observables and fields here, and the names in aliases.yaml and
centrality_definitions.yaml.

Adding an observable or a field is an edit to this file.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import yamlio

FORMAT_VERSION = 1

SYSTEMS = ("pp", "pPb", "PbPb", "XeXe", "AuAu", "OO", "NeNe")
EXPERIMENTS = ("ALICE", "ATLAS", "CMS", "LHCb", "STAR", "PHENIX", "PHOBOS", "BRAHMS")
ERROR_ORIGINS = ("description", "paper", "manual")

# What a spectrum is: the convention of a cross section or yield.
DEFINITIONS = (
    "CROSS_SECTION_DPT_DETA",          # d^2 sigma / dpT deta
    "CROSS_SECTION_DPT_DY",            # d^2 sigma / dpT dy
    "INVARIANT_CROSS_SECTION_DETA",    # 1/(2 pi pT) d^2 sigma / dpT deta
    "INVARIANT_CROSS_SECTION_DY",      # 1/(2 pi pT) d^2 sigma / dpT dy
    "YIELD_DPT_DETA",                  # 1/N_evt d^2 N / dpT deta
    "YIELD_DPT_DY",                    # 1/N_evt d^2 N / dpT dy
    "INVARIANT_YIELD_DETA",            # 1/N_evt 1/(2 pi pT) d^2 N / dpT deta
    "INVARIANT_YIELD_DY",              # 1/N_evt 1/(2 pi pT) d^2 N / dpT dy
    "YIELD_PER_TAA_DPT_DETA",          # the yield divided by <T_AA> (or <T_pA>)
    "YIELD_PER_TAA_DPT_DY",
    "INVARIANT_YIELD_PER_TAA_DETA",
    "INVARIANT_YIELD_PER_TAA_DY",
)  # fmt: skip

METHODS = ("SP", "EP", "2PC", "cumulant2", "cumulant4", "cumulant6", "cumulant8")


@dataclass(frozen=True)
class Field:
    """A dataset field beyond the ones every dataset has.

    kind: range ([lo, hi], lo < hi), integer (>= 1), number (>= 0), token (a short label
    with no underscores), or a tuple of the allowed values. where: the top level, `y` or
    `acceptance`.
    """

    kind: Any
    where: str = "top"


FIELDS: dict[str, Field] = {
    "centrality": Field("range"),                    # [lo, hi] in per cent; minimum bias [0, 100]
    "centrality_definition": Field("centrality_definition"),  # a name in centrality_definitions.yaml
    "reference_centrality": Field("range"),          # the class an R_CP is divided by
    "harmonic": Field("integer"),                    # the flow harmonic n
    "method": Field(METHODS),                        # how v_n was measured
    "definition": Field(DEFINITIONS, where="y"),
    "variant": Field("token"),                       # tells apart datasets nothing else does
    "eta_range": Field("range", where="acceptance"),
    "abs_eta_range": Field("range", where="acceptance"),  # |eta| in [lo, hi] with lo > 0
    "y_range": Field("range", where="acceptance"),
    "pt_range": Field("range", where="acceptance"),  # a fixed pT window when x is not pT
    "delta_eta_gap": Field("number", where="acceptance"),  # the eta gap of v_n{2}
}

# Acceptance fields any observable may have.
ACCEPTANCE = ("eta_range", "abs_eta_range", "y_range", "pt_range")


@dataclass(frozen=True)
class Observable:
    y: str
    systems: tuple[str, ...]
    required: tuple[str, ...]
    optional: tuple[str, ...] = ()
    # Fields that follow the class in the key, in this order, when a dataset has them.
    distinguish: tuple[str, ...] = ()
    key_format: dict[str, str] = field(default_factory=dict)
    # The CapeTownEloss final observable that computes it: a name, or
    # (field, {value: name}) for the values of that field the model can compute.
    final: Any = None
    x: tuple[str, ...] = ("pt",)

    @property
    def fields(self) -> tuple[str, ...]:
        return self.required + self.optional + ACCEPTANCE


_HEAVY_ION = ("pPb", "PbPb", "XeXe", "AuAu", "OO", "NeNe")

OBSERVABLES: dict[str, Observable] = {
    "raa": Observable(
        y="raa",
        systems=_HEAVY_ION,
        required=("centrality", "centrality_definition"),
        optional=("variant",),
        distinguish=("variant",),
        final="HADRON_RAA",
    ),
    "rcp": Observable(
        y="rcp",
        systems=_HEAVY_ION,
        required=("centrality", "centrality_definition", "reference_centrality"),
        optional=("variant",),
        distinguish=("variant",),
        final="HADRON_RAA",  # with reference = { centrality = [...] }
    ),
    "vn": Observable(
        y="vn",
        systems=_HEAVY_ION,
        required=("centrality", "centrality_definition", "harmonic", "method"),
        optional=("delta_eta_gap", "variant"),
        distinguish=("method", "harmonic", "delta_eta_gap", "variant"),
        key_format={"harmonic": "n{}", "delta_eta_gap": "gap{}"},
        final=("method", {"SP": "HADRON_VN_SP"}),
    ),
    "pp_cross_section": Observable(
        y="cross_section",
        systems=("pp",),
        required=("definition",),
        optional=("variant",),
        distinguish=("definition", "variant"),
        final=("definition", {d: "HADRON_CROSS_SECTION" for d in DEFINITIONS if "CROSS" in d}),
    ),
}


# --- the vocabulary files -----------------------------------------------------------------


@dataclass(frozen=True)
class Aliases:
    """aliases.yaml: raw spellings of error labels, x names and units -> common names."""

    errors: dict[str, tuple[str, ...]]
    x: dict[str, tuple[str, ...]]
    units: dict[str, tuple[str, ...]]

    @staticmethod
    def _reverse(table: dict[str, tuple[str, ...]], raw: str) -> str | None:
        return next((name for name, spellings in table.items() if raw in spellings), None)

    def error_name(self, raw: str) -> str | None:
        return self._reverse(self.errors, raw)

    def x_name(self, raw: str) -> str | None:
        return self._reverse(self.x, raw)

    def unit(self, raw: str) -> str | None:
        return self._reverse(self.units, raw)


class VocabularyError(ValueError):
    """aliases.yaml or centrality_definitions.yaml is malformed."""


def _table(path: Path, section: Any, what: str) -> dict[str, tuple[str, ...]]:
    seen: dict[str, str] = {}
    out: dict[str, tuple[str, ...]] = {}
    for name, spellings in (section or {}).items():
        if not isinstance(spellings, list):
            raise VocabularyError(f"{path.name}: {what}.{name} must be a list of strings")
        for spelling in spellings:
            if spelling in seen:
                raise VocabularyError(
                    f"{path.name}: {what} label {spelling!r} is under both '{seen[spelling]}' "
                    f"and '{name}'"
                )
            seen[spelling] = str(name)
        out[str(name)] = tuple(str(s) for s in spellings)
    return out


@lru_cache(maxsize=8)
def aliases(root: str | Path) -> Aliases:
    path = Path(root) / "aliases.yaml"
    raw = yamlio.load(path) or {}
    unknown = set(raw) - {"errors", "x", "units"}
    if unknown:
        raise VocabularyError(f"{path.name}: unknown sections {sorted(unknown)}")
    return Aliases(
        errors=_table(path, raw.get("errors"), "errors"),
        x=_table(path, raw.get("x"), "x"),
        units=_table(path, raw.get("units"), "units"),
    )


@lru_cache(maxsize=8)
def centrality_definitions(root: str | Path) -> dict[str, str]:
    """Each centrality definition's name and the experiment it belongs to."""
    path = Path(root) / "centrality_definitions.yaml"
    raw = (yamlio.load(path) if path.exists() else None) or {}
    out = {}
    for name, entry in raw.items():
        if not isinstance(entry, dict) or entry.get("experiment") not in EXPERIMENTS:
            raise VocabularyError(f"{path.name}: {name} needs an experiment from {EXPERIMENTS}")
        out[str(name)] = entry["experiment"]
    return out


# --- keys and lookups ---------------------------------------------------------------------


def lookup(dataset: dict[str, Any], name: str) -> Any:
    """A field's value in a dataset, wherever the field lives."""
    place = FIELDS[name].where
    if place == "top":
        return dataset.get(name)
    return (dataset.get(place) or {}).get(name)


def class_label(centrality: Any) -> str:
    lo, hi = centrality
    return f"{lo:g}-{hi:g}"


def _component(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "_".join(_component(v) for v in value)
    if isinstance(value, float) or (isinstance(value, int) and not isinstance(value, bool)):
        return f"{value:g}"
    return str(value)


def make_key(dataset: dict[str, Any]) -> str:
    """``observable__system+sqrt_s__experiment__particle__class`` plus distinguishing fields."""
    observable = OBSERVABLES[dataset["observable"]]
    parts = [
        dataset["observable"],
        f"{dataset['system']}{dataset['sqrt_s_nn']:g}",
        dataset["experiment"],
        dataset["particle"],
    ]
    if dataset.get("centrality") is not None:
        parts.append(class_label(dataset["centrality"]))
    for name in observable.distinguish:
        value = lookup(dataset, name)
        if value is not None:
            parts.append(observable.key_format.get(name, "{}").format(_component(value)))
    return "__".join(parts)


def final_kind(dataset: dict[str, Any]) -> str | None:
    """The CapeTownEloss final that computes this dataset, if there is one."""
    final = OBSERVABLES[dataset["observable"]].final
    if final is None or isinstance(final, str):
        return final
    by, kinds = final
    return kinds.get(lookup(dataset, by))


def dataset_path(root: str | Path, dataset: dict[str, Any]) -> Path:
    """Where a generated dataset file lives under ``curated/``."""
    folder = f"{dataset['system']}{dataset['sqrt_s_nn']:g}"
    return Path(root) / "curated" / dataset["observable"] / folder / f"{dataset['key']}.yaml"
