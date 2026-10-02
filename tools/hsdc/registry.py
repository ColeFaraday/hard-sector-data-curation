"""The vocabulary: aliases.yaml, centrality_definitions.yaml and observables.yaml.

Everything a dataset may say is defined in those three files or in the constants here, so
that the schema, the build and the reader agree on it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import yamlio

FORMAT_VERSION = 1

SYSTEMS = ("pp", "pPb", "PbPb", "XeXe", "AuAu", "OO", "NeNe")
EXPERIMENTS = ("ALICE", "ATLAS", "CMS", "LHCb", "STAR", "PHENIX", "PHOBOS", "BRAHMS")
CENTRALITY_QUANTITIES = (
    "charged_multiplicity",
    "energy",
    "transverse_energy",
    "impact_parameter",
    "event_selection",
)
ERROR_ORIGINS = ("description", "paper", "manual")
FIELD_TYPES = ("range", "integer", "number", "enum", "token", "centrality_definition")
FIELD_PLACES = ("top", "y", "acceptance")

_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class RegistryError(ValueError):
    """A registry file is malformed or contradicts another."""


@dataclass(frozen=True)
class Field:
    name: str
    type: str
    where: str = "top"
    values: tuple[str, ...] = ()
    minimum: float | None = None
    is_global: bool = False
    description: str = ""


@dataclass(frozen=True)
class Observable:
    name: str
    y: str
    x: tuple[str, ...]
    systems: tuple[str, ...]
    required: tuple[str, ...]
    optional: tuple[str, ...]
    distinguish: tuple[str, ...]
    key_format: dict[str, str]
    # None, a final's name, or {"by": field, "kinds": {value: final}}.
    final: Any = None

    @property
    def fields(self) -> tuple[str, ...]:
        return self.required + self.optional


@dataclass(frozen=True)
class CentralityDefinition:
    name: str
    experiment: str
    quantity: str
    detector: str
    eta_range: tuple[tuple[float, float], ...]
    pt_range: tuple[float, float] | None
    reference: str
    note: str


@dataclass
class Registry:
    root: Path
    errors: dict[str, tuple[str, ...]] = field(default_factory=dict)
    x_names: dict[str, tuple[str, ...]] = field(default_factory=dict)
    units: dict[str, tuple[str, ...]] = field(default_factory=dict)
    centrality: dict[str, CentralityDefinition] = field(default_factory=dict)
    fields: dict[str, Field] = field(default_factory=dict)
    observables: dict[str, Observable] = field(default_factory=dict)

    def error_name(self, raw_label: str) -> str | None:
        for name, labels in self.errors.items():
            if raw_label in labels:
                return name
        return None

    def x_name(self, raw: str) -> str | None:
        return _reverse(self.x_names, raw)

    def unit(self, raw: str) -> str | None:
        return _reverse(self.units, raw)


def _reverse(table: dict[str, tuple[str, ...]], raw: str) -> str | None:
    for name, spellings in table.items():
        if raw in spellings:
            return name
    return None


def _fail(path: Path, message: str) -> RegistryError:
    return RegistryError(f"{path.name}: {message}")


def _vocabulary(path: Path, section: Any, what: str) -> dict[str, tuple[str, ...]]:
    """A mapping from a common name to the raw spellings it stands for."""
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise _fail(path, f"'{what}' must map common names to lists of raw labels")
    seen: dict[str, str] = {}
    result: dict[str, tuple[str, ...]] = {}
    for name, spellings in section.items():
        if what != "units" and not _NAME.match(str(name)):
            raise _fail(path, f"{what} name {name!r} must be lower-case letters, digits and _")
        if not isinstance(spellings, list) or not all(isinstance(s, str) for s in spellings):
            raise _fail(path, f"{what}.{name} must be a list of strings")
        for spelling in spellings:
            if spelling in seen:
                raise _fail(
                    path,
                    f"{what} label {spelling!r} is listed under both '{seen[spelling]}' and "
                    f"'{name}'",
                )
            seen[spelling] = str(name)
        result[str(name)] = tuple(spellings)
    return result


def _ranges(path: Path, name: str, value: Any) -> tuple[tuple[float, float], ...]:
    if value is None:
        return ()
    if (
        isinstance(value, list)
        and len(value) == 2
        and all(isinstance(v, (int, float)) for v in value)
    ):
        value = [value]
    out = []
    for window in value:
        if (
            not isinstance(window, list)
            or len(window) != 2
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in window)
            or window[0] >= window[1]
        ):
            raise _fail(path, f"{name}: every window must be [lo, hi] with lo < hi")
        out.append((float(window[0]), float(window[1])))
    return tuple(out)


def _load_centrality(path: Path) -> dict[str, CentralityDefinition]:
    if not path.exists():
        return {}
    raw = yamlio.load(path) or {}
    if not isinstance(raw, dict):
        raise _fail(path, "must map names to definitions")
    allowed = {"experiment", "quantity", "detector", "eta_range", "pt_range", "reference", "note"}
    result: dict[str, CentralityDefinition] = {}
    for name, entry in raw.items():
        if not re.match(r"^[A-Z][A-Z0-9_]*$", str(name)):
            raise _fail(path, f"definition name {name!r} must be upper case letters, digits and _")
        if not isinstance(entry, dict):
            raise _fail(path, f"{name} must be a mapping")
        unknown = set(entry) - allowed
        if unknown:
            raise _fail(path, f"{name}: unknown keys {sorted(unknown)}")
        for key in ("experiment", "quantity", "detector", "reference"):
            if not entry.get(key):
                raise _fail(path, f"{name}: '{key}' is required")
        if entry["experiment"] not in EXPERIMENTS:
            raise _fail(path, f"{name}: experiment must be one of {list(EXPERIMENTS)}")
        if entry["quantity"] not in CENTRALITY_QUANTITIES:
            raise _fail(path, f"{name}: quantity must be one of {list(CENTRALITY_QUANTITIES)}")
        pt = entry.get("pt_range")
        pt_range = _ranges(path, f"{name}.pt_range", pt)
        result[str(name)] = CentralityDefinition(
            name=str(name),
            experiment=entry["experiment"],
            quantity=entry["quantity"],
            detector=str(entry["detector"]),
            eta_range=_ranges(path, f"{name}.eta_range", entry.get("eta_range")),
            pt_range=pt_range[0] if pt_range else None,
            reference=str(entry["reference"]),
            note=str(entry.get("note") or ""),
        )
    return result


def _load_fields(path: Path, section: Any) -> dict[str, Field]:
    if not isinstance(section, dict):
        raise _fail(path, "'fields' must be a mapping")
    result: dict[str, Field] = {}
    for name, entry in section.items():
        if not _NAME.match(str(name)):
            raise _fail(path, f"field name {name!r} must be lower-case letters, digits and _")
        if not isinstance(entry, dict) or entry.get("type") not in FIELD_TYPES:
            raise _fail(path, f"fields.{name}.type must be one of {list(FIELD_TYPES)}")
        where = entry.get("where", "top")
        if where not in FIELD_PLACES:
            raise _fail(path, f"fields.{name}.where must be one of {list(FIELD_PLACES)}")
        values = tuple(entry.get("values", ()))
        if entry["type"] == "enum" and not values:
            raise _fail(path, f"fields.{name}: an enum needs 'values'")
        result[str(name)] = Field(
            name=str(name),
            type=entry["type"],
            where=where,
            values=values,
            minimum=entry.get("minimum"),
            is_global=bool(entry.get("global", False)),
            description=str(entry.get("description", "")),
        )
    return result


def _load_observables(
    path: Path, section: Any, fields: dict[str, Field], x_names: dict[str, Any]
) -> dict[str, Observable]:
    if not isinstance(section, dict) or not section:
        raise _fail(path, "'observables' must be a non-empty mapping")
    result: dict[str, Observable] = {}
    allowed = {"y", "x", "systems", "required", "optional", "distinguish", "key_format", "final"}
    for name, entry in section.items():
        if not _NAME.match(str(name)):
            raise _fail(path, f"observable name {name!r} must be lower-case letters, digits and _")
        if not isinstance(entry, dict):
            raise _fail(path, f"{name} must be a mapping")
        unknown = set(entry) - allowed
        if unknown:
            raise _fail(path, f"{name}: unknown keys {sorted(unknown)}")
        x = tuple(entry.get("x", ()))
        if not x or any(v not in x_names for v in x):
            raise _fail(path, f"{name}.x must list names from aliases.yaml 'x'; got {list(x)}")
        systems = tuple(entry.get("systems", ()))
        if not systems or any(s not in SYSTEMS for s in systems):
            raise _fail(path, f"{name}.systems must list some of {list(SYSTEMS)}")
        lists: dict[str, tuple[str, ...]] = {}
        for key in ("required", "optional", "distinguish"):
            lists[key] = tuple(entry.get(key, ()))
            for item in lists[key]:
                if item not in fields:
                    raise _fail(path, f"{name}.{key}: '{item}' is not in 'fields'")
        for item in lists["distinguish"]:
            if item not in lists["required"] + lists["optional"] and not fields[item].is_global:
                raise _fail(path, f"{name}.distinguish: '{item}' must be required or optional")
        key_format = dict(entry.get("key_format", {}))
        for item in key_format:
            if item not in lists["distinguish"]:
                raise _fail(path, f"{name}.key_format: '{item}' is not in distinguish")
            if "{}" not in key_format[item]:
                raise _fail(path, f"{name}.key_format.{item} must contain {{}}")
        final = entry.get("final")
        if isinstance(final, dict):
            if set(final) != {"by", "kinds"} or final["by"] not in fields:
                raise _fail(path, f"{name}.final must be a name or {{by: <field>, kinds: {{..}}}}")
        elif final is not None and not isinstance(final, str):
            raise _fail(path, f"{name}.final must be a name or {{by: <field>, kinds: {{..}}}}")
        result[str(name)] = Observable(
            name=str(name),
            y=str(entry.get("y", name)),
            x=x,
            systems=systems,
            required=lists["required"],
            optional=lists["optional"],
            distinguish=lists["distinguish"],
            key_format=key_format,
            final=final,
        )
    return result


def load(root: str | Path) -> Registry:
    """Read the three vocabulary files under ``root``."""
    root = Path(root)
    aliases_path = root / "aliases.yaml"
    raw = yamlio.load(aliases_path) or {}
    registry = Registry(root=root)
    registry.errors = _vocabulary(aliases_path, raw.get("errors"), "errors")
    registry.x_names = _vocabulary(aliases_path, raw.get("x"), "x")
    registry.units = _vocabulary(aliases_path, raw.get("units"), "units")
    unknown = set(raw) - {"errors", "x", "units"}
    if unknown:
        raise _fail(aliases_path, f"unknown sections {sorted(unknown)}")

    registry.centrality = _load_centrality(root / "centrality_definitions.yaml")

    obs_path = root / "observables.yaml"
    obs = yamlio.load(obs_path) or {}
    registry.fields = _load_fields(obs_path, obs.get("fields"))
    registry.observables = _load_observables(
        obs_path, obs.get("observables"), registry.fields, registry.x_names
    )
    return registry


def _component(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "_".join(_component(v) for v in value)
    if isinstance(value, float) or (isinstance(value, int) and not isinstance(value, bool)):
        return f"{value:g}"
    return str(value)


def class_label(centrality: Any) -> str:
    lo, hi = centrality
    return f"{lo:g}-{hi:g}"


def lookup(dataset: dict[str, Any], registry: Registry, name: str) -> Any:
    """A field's value in a dataset, wherever the field lives."""
    place = registry.fields[name].where
    if place == "top":
        return dataset.get(name)
    return (dataset.get(place) or {}).get(name)


def make_key(dataset: dict[str, Any], registry: Registry) -> str:
    """``observable__system+sqrt_s__experiment__particle__class`` plus distinguishing fields."""
    obs = registry.observables[dataset["observable"]]
    parts = [
        dataset["observable"],
        f"{dataset['system']}{dataset['sqrt_s_nn']:g}",
        dataset["experiment"],
        dataset["particle"],
    ]
    if dataset.get("centrality") is not None:
        parts.append(class_label(dataset["centrality"]))
    for name in obs.distinguish:
        value = lookup(dataset, registry, name)
        if value is None:
            continue
        text = _component(value)
        parts.append(obs.key_format.get(name, "{}").format(text))
    return "__".join(parts)


def final_kind(observable: Observable, dataset: dict[str, Any], registry: Registry) -> str | None:
    """The CapeTownEloss final that computes this dataset's observable, if there is one."""
    final = observable.final
    if final is None or isinstance(final, str):
        return final
    value = lookup(dataset, registry, final["by"])
    return final["kinds"].get(value)


def dataset_path(root: str | Path, dataset: dict[str, Any]) -> Path:
    """Where a generated dataset file lives under ``curated/``."""
    folder = f"{dataset['system']}{dataset['sqrt_s_nn']:g}"
    return Path(root) / "curated" / dataset["observable"] / folder / f"{dataset['key']}.yaml"
