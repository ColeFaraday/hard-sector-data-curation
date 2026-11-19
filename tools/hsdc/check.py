"""The format check of one dataset: what the build guarantees, checked again on any file,
including the hand-written ones in manual/."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import vocab

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]*$")  # no underscores: never a key separator
_WORD = re.compile(r"^[A-Za-z0-9]+(_[A-Za-z0-9]+)*$")
_BASE = ("format_version", "key", "observable", "system", "sqrt_s_nn", "experiment",
         "particle", "source", "x", "y", "errors", "bins")  # fmt: skip
_HEPDATA = {"inspire_id", "version", "table", "column", "location", "doi"}
_SOURCE = {"hepdata", "paper", "figure", "inspireHEPKey"}
_ERROR_KEYS = {"label", "origin", "reference", "entered_by", "percent", "relative", "note"}


def _number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _error_value(x: Any) -> bool:
    """A symmetric error, or [minus, plus]; null where HEPData had a placeholder."""
    if isinstance(x, list):
        return len(x) == 2 and all(v is None or _number(v) for v in x)
    return x is None or _number(x)


def _field_problem(name: str, value: Any, root: Path) -> str | None:
    kind = vocab.FIELDS[name].kind
    if kind == "range":
        ok = isinstance(value, list) and len(value) == 2 and all(map(_number, value))
        if not ok or value[0] >= value[1]:
            return f"{name} {value!r} must be [lo, hi] with lo < hi"
        if name in ("centrality", "reference_centrality") and not 0 <= value[0] < value[1] <= 100:
            return f"{name} {value} must lie in [0, 100]"
    elif kind == "integer":
        if not (isinstance(value, int) and not isinstance(value, bool) and value >= 1):
            return f"{name} {value!r} must be an integer >= 1"
    elif kind == "number":
        if not (_number(value) and value >= 0):
            return f"{name} {value!r} must be a number >= 0"
    elif kind == "token":
        if not (isinstance(value, str) and _TOKEN.match(value)):
            return f"{name} {value!r} must be letters, digits, '.' and '-'"
    elif kind == "centrality_definition":
        definitions = vocab.centrality_definitions(root)
        if value not in definitions:
            return f"centrality_definition {value!r} is not in centrality_definitions.yaml"
    elif value not in kind:
        return f"{name} {value!r} must be one of {list(kind)}"
    return None


def problems(dataset: Any, root: str | Path) -> list[str]:
    """Everything wrong with a dataset's format; empty when it is fine."""
    root = Path(root)
    if not isinstance(dataset, dict):
        return ["a dataset must be a mapping"]
    missing = [k for k in _BASE if k not in dataset]
    if missing:
        return [f"missing {missing}"]
    out: list[str] = []
    if dataset["format_version"] != vocab.FORMAT_VERSION:
        out.append(f"format_version must be {vocab.FORMAT_VERSION}")
    observable = vocab.OBSERVABLES.get(dataset["observable"])
    if observable is None:
        return [f"observable {dataset['observable']!r} is not one of {sorted(vocab.OBSERVABLES)}"]
    if dataset["system"] not in observable.systems:
        out.append(f"system {dataset['system']!r} is not one of {list(observable.systems)}")
    if not (_number(dataset["sqrt_s_nn"]) and dataset["sqrt_s_nn"] > 0):
        out.append("sqrt_s_nn must be a positive number")
    if dataset["experiment"] not in vocab.EXPERIMENTS:
        out.append(f"experiment {dataset['experiment']!r} is not one of {list(vocab.EXPERIMENTS)}")
    if not (isinstance(dataset["particle"], str) and _WORD.match(dataset["particle"])):
        out.append(f"particle {dataset['particle']!r} must be a word")

    # Fields: only the observable's, each well formed, the required ones present.
    allowed = set(observable.fields)
    places = {"top": dataset, "y": dataset["y"], "acceptance": dataset.get("acceptance") or {}}
    fixed = {"top": set(_BASE) | {"acceptance", "note"}, "y": {"name", "units"}, "acceptance": set()}
    for place, mapping in places.items():
        if not isinstance(mapping, dict):
            out.append(f"{place} must be a mapping")
            continue
        for name, value in mapping.items():
            if name in fixed[place]:
                continue
            spec = vocab.FIELDS.get(name)
            if spec is None or spec.where != place or name not in allowed:
                out.append(f"{name} is not a field of observable {dataset['observable']}")
                continue
            problem = _field_problem(name, value, root)
            if problem:
                out.append(problem)
    for name in observable.required:
        if vocab.lookup(dataset, name) is None:
            out.append(f"observable {dataset['observable']} needs {name}")
    definition = dataset.get("centrality_definition")
    owner = vocab.centrality_definitions(root).get(definition or "")
    if owner is not None and owner != dataset["experiment"]:
        out.append(f"centrality_definition {definition} belongs to {owner}, not {dataset['experiment']}")

    # Source, x and y.
    source = dataset["source"]
    if not isinstance(source, dict) or set(source) - _SOURCE or not ({"hepdata", "paper"} & set(source)):
        out.append("source needs hepdata or paper, and only " + ", ".join(sorted(_SOURCE)))
    elif "hepdata" in source:
        hepdata = source["hepdata"]
        if set(hepdata) - _HEPDATA or not {"inspire_id", "version", "table", "column"} <= set(hepdata):
            out.append("source.hepdata needs inspire_id, version, table and column")
    aliases = vocab.aliases(root)
    x = dataset["x"]
    if x.get("name") not in observable.x or x.get("units") not in aliases.units or set(x) - {"name", "units"}:
        out.append(f"x must be {{name: one of {list(observable.x)}, units: a name in aliases.yaml}}")
    if dataset["y"].get("name") != observable.y:
        out.append(f"y.name must be {observable.y!r}")

    # Error sources: declared ones are named in aliases.yaml, and are exactly those the bins use.
    declared = dataset["errors"] or {}
    for name, definition in declared.items():
        if name not in aliases.errors:
            out.append(f"error source {name!r} is not a name in aliases.yaml")
        if not isinstance(definition, dict) or set(definition) - _ERROR_KEYS:
            out.append(f"errors.{name} may only have {sorted(_ERROR_KEYS)}")
            continue
        if ("label" in definition) == ("origin" in definition):
            out.append(f"errors.{name} needs a label (from the table) or an origin, not both")
        origin = definition.get("origin")
        if origin is not None and origin not in vocab.ERROR_ORIGINS:
            out.append(f"errors.{name}.origin must be one of {list(vocab.ERROR_ORIGINS)}")
        if origin == "paper" and not definition.get("reference"):
            out.append(f"errors.{name}: origin paper needs a reference")
        if origin == "manual" and not definition.get("entered_by"):
            out.append(f"errors.{name}: origin manual needs entered_by")

    # Bins: one form, in order, numbers where numbers go.
    bins = dataset["bins"]
    if not isinstance(bins, list) or not bins:
        return out + ["bins must be a non-empty list"]
    used: set[str] = set()
    forms = set()
    for index, entry in enumerate(bins):
        if not isinstance(entry, dict) or set(entry) - {"low", "high", "centre", "value", "errors"}:
            out.append(f"bin {index} may only have low, high, centre, value and errors")
            continue
        forms.add(("low" in entry, "high" in entry, "centre" in entry))
        if not (entry.get("value") is None or _number(entry["value"])) or "value" not in entry:
            out.append(f"bin {index}: value must be a number or null")
        for key in ("low", "high", "centre"):
            if key in entry and not _number(entry[key]):
                out.append(f"bin {index}: {key} must be a number")
        if "low" in entry and "high" in entry and not entry["low"] < entry["high"]:
            out.append(f"bin {index}: low {entry['low']} is not below high {entry['high']}")
        for name, value in (entry.get("errors") or {}).items():
            used.add(name)
            if not _error_value(value):
                out.append(f"bin {index}: error {name} must be a number, null or [minus, plus]")
    if len(forms) != 1 or next(iter(forms))[0] != next(iter(forms))[1]:
        out.append("every bin needs the same form: low and high, a centre, or both")
    elif next(iter(forms))[0]:
        for a, b in zip(bins, bins[1:]):
            if b["low"] < a["high"]:
                out.append(f"bins overlap or run backwards: [{a['low']}, {a['high']}] then [{b['low']}, {b['high']}]")
                break
    elif any(b["centre"] <= a["centre"] for a, b in zip(bins, bins[1:])):
        out.append("centres are not strictly increasing")
    if used - set(declared):
        out.append(f"bins use undeclared error sources {sorted(used - set(declared))}")
    if set(declared) - used:
        out.append(f"declared error sources never used by a bin: {sorted(set(declared) - used)}")

    if not out and dataset["key"] != vocab.make_key(dataset):
        out.append(f"key is {dataset['key']!r} but its fields make {vocab.make_key(dataset)!r}")
    return out
