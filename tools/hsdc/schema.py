"""schema/dataset.schema.json, generated from the registry, and the checks on top of it.

JSON Schema covers the shape of a dataset. What it cannot say is checked in
``semantic_problems``: the key, the order of bins, and the agreement between the error
sources a dataset declares and the ones its bins use.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

from . import registry as reg
from .registry import Field, Observable, Registry

_NUMBER = {"type": "number"}
_NULLABLE = {"type": ["number", "null"]}
_PAIR = {"type": "array", "minItems": 2, "maxItems": 2, "items": _NULLABLE}
_ERROR_VALUE = {"anyOf": [_NULLABLE, _PAIR]}
_STRING = {"type": "string", "minLength": 1}
# `false` loses the property's path in an error, so a field is forbidden with `not: {}`.
_FORBIDDEN = {"not": {}}
_RANGE = {"type": "array", "minItems": 2, "maxItems": 2, "items": _NUMBER}
_SOURCES = ("hepdata", "paper")

# A free label for a key: no underscores, so it never looks like a field separator.
_TOKEN = r"^[A-Za-z0-9][A-Za-z0-9.\-]*$"

# Single underscores inside a word; a double one separates the fields of a key.
_WORD = r"^[A-Za-z0-9]+(_[A-Za-z0-9]+)*$"


def _field_schema(field: Field, registry: Registry) -> Any:
    if field.type == "range":
        return _RANGE
    if field.type in ("integer", "number"):
        schema: dict[str, Any] = {"type": field.type}
        if field.minimum is not None:
            schema["minimum"] = field.minimum
        return schema
    if field.type == "enum":
        return {"enum": list(field.values)}
    if field.type == "token":
        return {"type": "string", "pattern": _TOKEN}
    if field.type == "centrality_definition":
        names = sorted(registry.centrality)
        return {"enum": names} if names else _FORBIDDEN
    raise AssertionError(field.type)


def _observable_rule(observable: Observable, registry: Registry) -> dict[str, Any]:
    top_required = [n for n in observable.required if registry.fields[n].where == "top"]
    y_required = ["name"] + [n for n in observable.required if registry.fields[n].where == "y"]
    if len(y_required) > 1:
        y_required.append("units")
    acceptance_required = [
        n for n in observable.required if registry.fields[n].where == "acceptance"
    ]
    then: dict[str, Any] = {
        "properties": {
            "system": {"enum": list(observable.systems)},
            "x": {"properties": {"name": {"enum": list(observable.x)}}},
            "y": {"required": y_required, "properties": {"name": {"const": observable.y}}},
        }
    }
    if top_required:
        then["required"] = top_required
    if acceptance_required:
        then["properties"]["acceptance"] = {"required": acceptance_required}
    allowed = set(observable.fields)
    for name, field in registry.fields.items():
        if field.where == "top" and name not in allowed:
            then["properties"][name] = _FORBIDDEN
    return {"if": {"properties": {"observable": {"const": observable.name}}}, "then": then}


def dataset_schema(registry: Registry) -> dict[str, Any]:
    error_names = sorted(registry.errors)
    top: dict[str, Any] = {
        "format_version": {"const": reg.FORMAT_VERSION},
        "key": _STRING,
        "observable": {"enum": sorted(registry.observables)},
        "system": {"enum": list(reg.SYSTEMS)},
        "sqrt_s_nn": {"type": "number", "exclusiveMinimum": 0},
        "experiment": {"enum": list(reg.EXPERIMENTS)},
        "particle": {"type": "string", "pattern": _WORD},
        "source": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "hepdata": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["inspire_id", "version", "table", "column"],
                    "properties": {
                        "inspire_id": {"type": "integer", "minimum": 1},
                        "version": {"type": "integer", "minimum": 1},
                        "table": _STRING,
                        "column": {"type": "integer", "minimum": 0},
                        "location": _STRING,
                        "doi": _STRING,
                    },
                },
                "paper": _STRING,
                "figure": _STRING,
                "inspireHEPKey": _STRING,
            },
            "anyOf": [{"required": [name]} for name in _SOURCES],
        },
        "note": _STRING,
        "x": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "units"],
            "properties": {
                "name": {"enum": sorted(registry.x_names)},
                "units": {"enum": sorted(registry.units)},
            },
        },
        "errors": {
            "type": "object",
            "propertyNames": {"enum": error_names},
            "additionalProperties": {"$ref": "#/$defs/errorSource"},
        },
        "bins": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/bin"}},
    }
    y_props: dict[str, Any] = {"name": _STRING, "units": _STRING}
    acceptance_props: dict[str, Any] = {}
    for name, field in registry.fields.items():
        if field.where == "top":
            top[name] = _field_schema(field, registry)
        elif field.where == "y":
            y_props[name] = _field_schema(field, registry)
        else:
            acceptance_props[name] = _field_schema(field, registry)
    top["y"] = {"type": "object", "additionalProperties": False, "properties": y_props}
    top["acceptance"] = {
        "type": "object",
        "additionalProperties": False,
        "properties": acceptance_props,
    }
    required = [
        "format_version",
        "key",
        "observable",
        "system",
        "sqrt_s_nn",
        "experiment",
        "particle",
        "source",
        "x",
        "y",
        "errors",
        "bins",
    ]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "dataset.schema.json",
        "title": "A curated experimental dataset",
        "description": "Generated from observables.yaml, aliases.yaml and "
        "centrality_definitions.yaml by `hsdc schema`; do not edit.",
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": top,
        "allOf": [_observable_rule(o, registry) for _, o in sorted(registry.observables.items())],
        "$defs": {
            "errorSource": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    # Empty when HEPData gave the error no label; the recipe then names it.
                    "label": {"type": "string"},
                    "origin": {"enum": list(reg.ERROR_ORIGINS)},
                    "reference": _STRING,
                    "entered_by": _STRING,
                    "percent": {"const": True},
                    "relative": _ERROR_VALUE,
                    "note": _STRING,
                },
                "oneOf": [{"required": ["label"]}, {"required": ["origin"]}],
                "allOf": [
                    {
                        "if": {"properties": {"origin": {"const": "paper"}}, "required": ["origin"]},
                        "then": {"required": ["reference"]},
                    },
                    {
                        "if": {
                            "properties": {"origin": {"const": "manual"}},
                            "required": ["origin"],
                        },
                        "then": {"required": ["entered_by"]},
                    },
                ],
            },
            "bin": {
                "type": "object",
                "additionalProperties": False,
                "required": ["value"],
                "properties": {
                    "low": _NUMBER,
                    "high": _NUMBER,
                    "centre": _NUMBER,
                    "value": _NULLABLE,
                    "errors": {"type": "object", "additionalProperties": _ERROR_VALUE},
                },
            },
        },
    }


def schema_text(registry: Registry) -> str:
    return json.dumps(dataset_schema(registry), indent=2, sort_keys=False) + "\n"


def write_schema(registry: Registry) -> Path:
    path = registry.root / "schema" / "dataset.schema.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = schema_text(registry)
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
    return path


def _path(error: jsonschema.ValidationError) -> str:
    return "/".join(str(p) for p in error.absolute_path) or "(top level)"


def schema_problems(dataset: Any, schema: dict[str, Any]) -> list[str]:
    validator = jsonschema.Draft202012Validator(schema)
    problems = []
    for error in sorted(validator.iter_errors(dataset), key=lambda e: list(map(str, e.path))):
        if error.validator == "not" and error.validator_value == _FORBIDDEN["not"]:
            problems.append(f"{_path(error)}: is not a field of observable {dataset.get('observable')}")
        else:
            problems.append(f"{_path(error)}: {error.message}")
    return problems


def _bin_form(entry: dict[str, Any]) -> tuple[bool, bool]:
    return ("low" in entry and "high" in entry, "centre" in entry)


def semantic_problems(dataset: dict[str, Any], registry: Registry) -> list[str]:
    """What the schema cannot say. Assumes the dataset already passed it."""
    problems: list[str] = []

    expected = reg.make_key(dataset, registry)
    if dataset["key"] != expected:
        problems.append(f"key is {dataset['key']!r} but its fields make {expected!r}")

    centrality = dataset.get("centrality")
    if centrality is not None and not 0 <= centrality[0] < centrality[1] <= 100:
        problems.append(f"centrality {centrality} must satisfy 0 <= lo < hi <= 100")
    reference = dataset.get("reference_centrality")
    if reference is not None and not 0 <= reference[0] < reference[1] <= 100:
        problems.append(f"reference_centrality {reference} must satisfy 0 <= lo < hi <= 100")
    for name, field in registry.fields.items():
        value = reg.lookup(dataset, registry, name)
        if field.type == "range" and field.where != "top" and value is not None:
            if value[0] >= value[1]:
                problems.append(f"{name} {value} must have lo < hi")

    definition = dataset.get("centrality_definition")
    if definition is not None and definition in registry.centrality:
        owner = registry.centrality[definition].experiment
        if owner != dataset["experiment"]:
            problems.append(
                f"centrality_definition {definition} belongs to {owner}, "
                f"not {dataset['experiment']}"
            )

    declared = set(dataset["errors"])
    used: set[str] = set()
    forms = {_bin_form(entry) for entry in dataset["bins"]}
    if len(forms) != 1:
        problems.append("bins mix edges and centres: every bin must have the same form")
    for index, entry in enumerate(dataset["bins"]):
        used |= set(entry.get("errors", {}))
        low, high = entry.get("low"), entry.get("high")
        if (low is None) != (high is None):
            problems.append(f"bin {index}: low and high come together")
        elif low is not None and not low < high:
            problems.append(f"bin {index}: low {low} is not below high {high}")
    if used - declared:
        problems.append(f"bins use undeclared error sources {sorted(used - declared)}")
    if declared - used:
        problems.append(f"declared error sources never used by a bin: {sorted(declared - used)}")

    edges = [e for e in dataset["bins"] if "low" in e]
    if edges:
        for a, b in zip(edges, edges[1:]):
            if b["low"] < a["high"]:
                problems.append(
                    f"bins overlap or run backwards: [{a['low']}, {a['high']}] then "
                    f"[{b['low']}, {b['high']}]"
                )
                break
    else:
        centres = [e["centre"] for e in dataset["bins"]]
        if any(b <= a for a, b in zip(centres, centres[1:])):
            problems.append("centres are not strictly increasing")
    return problems
