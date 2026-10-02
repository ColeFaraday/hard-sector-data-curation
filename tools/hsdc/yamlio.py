"""Reading YAML, and writing dataset files so that a rebuild is byte-identical.

PyYAML's dumper chooses its own layout, so the dataset files are written here instead:
block mappings for the metadata and one flow mapping per bin, in the layout of
docs/format.md.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import yaml

_Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

_PLAIN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-/ ]*$")
# YAML 1.1 words that a plain scalar would turn into a bool or null.
_RESERVED = {"y", "n", "yes", "no", "true", "false", "on", "off", "null", "~"}
_WRAP = 96


def load(path: str | Path) -> Any:
    with open(path, encoding="utf-8") as handle:
        return yaml.load(handle, Loader=_Loader)


def load_all(path: str | Path) -> list[Any]:
    with open(path, encoding="utf-8") as handle:
        return list(yaml.load_all(handle, Loader=_Loader))


def loads(text: str) -> Any:
    return yaml.load(text, Loader=_Loader)


def number(x: int | float) -> str:
    """A number as YAML 1.1 reads it back as a number, with the digits repr gives."""
    if isinstance(x, bool):
        raise TypeError("a bool is not a number")
    if isinstance(x, int):
        return str(x)
    if math.isnan(x) or math.isinf(x):
        raise ValueError(f"cannot write {x!r}; a placeholder should have become null")
    text = repr(x)
    # PyYAML reads 1e-05 as a string: the mantissa needs its point.
    mantissa, exponent, tail = text.partition("e")
    if exponent and "." not in mantissa:
        text = f"{mantissa}.0e{tail}"
    return text


def string(text: str) -> str:
    if _PLAIN.match(text) and not text.endswith(" ") and text.lower() not in _RESERVED:
        return text
    return json.dumps(text, ensure_ascii=False)


def scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return number(value)
    if isinstance(value, str):
        return string(value)
    raise TypeError(f"not a scalar: {value!r}")


def flow(value: Any) -> str:
    """One-line flow form of a scalar, list or mapping."""
    if isinstance(value, dict):
        if not value:
            return "{}"
        inner = ", ".join(f"{string(str(k))}: {flow(v)}" for k, v in value.items())
        return "{ " + inner + " }"
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(flow(v) for v in value) + "]"
    return scalar(value)


def _wrapped(items: list[str], open_: str, close: str, column: int) -> str:
    """``open_``, the items and ``close``, wrapped at _WRAP columns.

    The text starts at ``column``; continuation lines line up with the first item.
    """
    indent = column + len(open_)
    lines: list[str] = []
    line = ""
    budget = _WRAP - indent
    for position, item in enumerate(items):
        piece = item + ("," if position + 1 < len(items) else "")
        if line and len(line) + 1 + len(piece) > budget:
            lines.append(line)
            line = piece
        else:
            line = f"{line} {piece}" if line else piece
    lines.append(line)
    return open_ + ("\n" + " " * indent).join(lines) + " " + close


def _bin_text(entry: dict[str, Any]) -> str:
    head = [f"{key}: {flow(entry[key])}" for key in ("low", "high", "centre", "value") if key in entry]
    errors = entry.get("errors")
    if not errors:
        return "  - { " + ", ".join(head) + " }"
    names = [f"{string(name)}: {flow(value)}" for name, value in errors.items()]
    inner = _wrapped(names, open_="errors: { ", close="}", column=6)
    return "  - { " + ", ".join(head) + ",\n      " + inner + " }"


def _is_wide(value: Any) -> bool:
    """A mapping too big for one line: more than three entries, or one that nests."""
    return isinstance(value, dict) and (
        len(value) > 3 or any(isinstance(v, dict) for v in value.values())
    )


def _block(value: dict[str, Any], indent: int) -> list[str]:
    """Block-style lines for a mapping. Small leaves stay in flow style."""
    pad = " " * indent
    lines: list[str] = []
    for key, item in value.items():
        label = string(str(key))
        if _is_wide(item):
            lines.append(f"{pad}{label}:")
            lines.extend(_block(item, indent + 2))
        else:
            lines.append(f"{pad}{label}: {flow(item)}")
    return lines


# Top-level layout of a dataset file. Keys not named here follow, in insertion order.
_ORDER = (
    "format_version",
    "key",
    "observable",
    "system",
    "sqrt_s_nn",
    "experiment",
    "particle",
    "centrality",
    "centrality_definition",
    "reference_centrality",
    "harmonic",
    "method",
    "acceptance",
    "source",
    "note",
    "x",
    "y",
    "errors",
    "bins",
)


def dump_dataset(dataset: dict[str, Any]) -> str:
    """Text of a dataset file; the same dataset always gives the same text."""
    keys = [k for k in _ORDER if k in dataset] + [k for k in dataset if k not in _ORDER]
    lines: list[str] = []
    for key in keys:
        value = dataset[key]
        if key == "bins":
            lines.append("bins:")
            lines.extend(_bin_text(entry) for entry in value)
        elif key == "errors" and value:
            lines.append("errors:")
            for name, definition in value.items():
                lines.append(f"  {string(name)}: {flow(definition)}")
        elif _is_wide(value):
            lines.append(f"{key}:")
            lines.extend(_block(value, 2))
        else:
            lines.append(f"{key}: {flow(value)}")
    return "\n".join(lines) + "\n"
