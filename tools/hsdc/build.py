"""Applying recipes to raw HEPData records.

The build copies numbers and signs as HEPData has them and checks the format. It never
decides anything about the physics: what a source is called comes from aliases.yaml, which
table holds which class comes from the recipe.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import raw, recipe as recipes, schema, yamlio
from .raw import Parsed, RawError, RawRecord, Table, Variable
from .recipe import Additional, DatasetSpec, Recipe
from .registry import FORMAT_VERSION, Registry, class_label, dataset_path, make_key


class BuildError(ValueError):
    """The recipe and the record disagree, or the result breaks the format."""


@dataclass
class Built:
    dataset: dict[str, Any]
    recipe: Path
    warnings: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return self.dataset["key"]


def round_sig(x: float, digits: int = 12) -> float:
    """A product rounded so that float noise does not reach the file."""
    return float(f"{x:.{digits}g}")


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


# --- qualifiers --------------------------------------------------------------------------

_CLASS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:-|\u2013|\u2014|to)\s*(\d+(?:\.\d+)?)", re.I)
_WINDOW = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(?:to|-|\u2013)\s*(-?\d+(?:\.\d+)?)\s*$", re.I)
_BELOW = re.compile(r"^\s*<\s*(\d+(?:\.\d+)?)\s*$")


def parse_window(text: str) -> tuple[float, float] | None:
    """[lo, hi] from '-1.0 TO 1.0', '-0.8 - 0.8', '< 1' or '< 0.8 (LAB)'; None if it is none."""
    text = re.sub(r"\([^)]*\)", "", text)  # a remark in brackets, such as (LAB)
    match = _WINDOW.match(text)
    if match:
        return float(match.group(1)), float(match.group(2))
    match = _BELOW.match(text)
    if match:
        return -float(match.group(1)), float(match.group(1))
    return None


def _centrality_problem(column: Variable, centrality: Any) -> tuple[str | None, str | None]:
    """(error, warning) from comparing the table's centrality qualifier with the recipe's."""
    qualifier = column.qualifier("CENTRALITY", "CENT")
    if qualifier is None or centrality is None:
        return None, None
    match = _CLASS.search(qualifier.value)
    if not match:
        return None, f"cannot read the centrality qualifier {qualifier.value!r}"
    seen = (float(match.group(1)), float(match.group(2)))
    if not (_close(seen[0], centrality[0]) and _close(seen[1], centrality[1])):
        return (
            f"the table says centrality {qualifier.value!r} but the recipe says "
            f"{list(centrality)}",
            None,
        )
    return None, None


_RATIO = re.compile(
    r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*%?\s*/\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)"
)


def _ratio_problem(column: Variable, centrality: Any, reference: Any) -> str | None:
    """Check a central-to-peripheral ratio's classes, where a qualifier says them as 0-5%/50-90%."""
    if centrality is None or reference is None:
        return None
    for qualifier in column.qualifiers:
        match = _RATIO.search(qualifier.value)
        if not match:
            continue
        numbers = [float(g) for g in match.groups()]
        if not all(_close(a, b) for a, b in zip(numbers, [*centrality, *reference])):
            return (
                f"the table says the ratio {qualifier.value!r} but the recipe says "
                f"{list(centrality)} over {list(reference)}"
            )
    return None


_REACTION = {
    "P P": "pp",
    "P PB": "pPb",
    "PB P": "pPb",
    "PB PB": "PbPb",
    "XE XE": "XeXe",
    "AU AU": "AuAu",
    "O O": "OO",
    "NE NE": "NeNe",
}
_ENERGY_NAMES = ("SQRT(S)/NUCLEON", "SQRT(S)", "SQRT(S_NN)")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _identity_warnings(column: Variable, system: str, sqrt_s_nn: float) -> list[str]:
    """Compare the collision system and energy the recipe gives with the table's qualifiers."""
    warnings = []
    reaction = column.qualifier("RE")
    if reaction is not None and "-->" in reaction.value:
        beams = " ".join(reaction.value.split("-->")[0].split()).upper()
        seen = _REACTION.get(beams)
        if seen is not None and seen != system:
            warnings.append(f"the table's reaction is {reaction.value!r} but the recipe says {system}")
    energy = column.qualifier(*_ENERGY_NAMES)
    found = _NUMBER.search(energy.value) if energy is not None else None
    if found:
        value = float(found.group())
        if "tev" in energy.value.lower() or value < 100:
            value *= 1000
        if not math.isclose(value, sqrt_s_nn, rel_tol=2e-3):
            warnings.append(f"the table's {energy.name} is {energy.value!r} but the recipe says {sqrt_s_nn:g}")
    return warnings


_ETA_NAMES = ("ETARAP", "TRACK ETA", "ETA", "ABS(ETA)", "ABS(ETARAP)", "$|\\eta|$")
_Y_NAMES = ("Y*", "YRAP", "Y")


def _acceptance_warning(column: Variable, acceptance: dict[str, Any]) -> str | None:
    """Compare the table's eta and rapidity windows with the recipe's. Only ever a warning."""
    for names, signed in ((_ETA_NAMES, "eta_range"), (_Y_NAMES, "y_range")):
        qualifier = column.qualifier(*names)
        window = parse_window(qualifier.value) if qualifier else None
        if qualifier is None or window is None:
            continue
        key, expected = signed, list(window)
        # |eta| in [0, hi] is the window [-hi, hi]; |eta| in [lo, hi] with lo > 0 is two windows.
        if (qualifier.name.upper().startswith("ABS(") or "|" in qualifier.name) and window[0] >= 0:
            if _close(window[0], 0.0):
                expected = [-window[1], window[1]]
            else:
                key = "abs_" + signed
        given = acceptance.get(key)
        if given is None:
            return f"the table gives {qualifier.name} {qualifier.value!r} but the recipe has no {key}"
        if not all(_close(a, b) for a, b in zip(given, expected)):
            return (
                f"the table gives {qualifier.name} {qualifier.value!r} "
                f"but the recipe has {key} {list(given)}"
            )
    return None


# --- descriptions ------------------------------------------------------------------------


def _class_pattern(centrality: Any) -> re.Pattern[str]:
    lo, hi = (re.escape(f"{v:g}") for v in centrality)
    return re.compile(
        rf"(?<![\d.]){lo}(?:\.0+)?\s*(?:-|\u2013|\u2014|to)\s*{hi}(?:\.0+)?(?![\d.])", re.I
    )


def description_supports(
    text: str, centrality: Any, magnitudes: list[float], sample: str | None = None
) -> bool:
    """Is every magnitude (a fraction) on one line of ``text`` that names the sample?

    The sample is the class when there is one, else whatever ``sample`` says, such as 'P-PB NSD'
    for a minimum-bias sample. With neither, the numbers only have to share a line. The
    class's own edges are removed from the line first, so '0-5' cannot be read as the number 5.
    """
    pattern = _class_pattern(centrality) if centrality is not None and sample is None else None
    for line in re.split(r"\n+", text):
        for sentence in re.split(r"(?<=[a-z%])\.\s+(?=[A-Z])", line):
            scrubbed = sentence
            if sample is not None:
                if sample.casefold() not in sentence.casefold():
                    continue
            elif pattern is not None:
                found = pattern.search(sentence)
                if not found:
                    continue
                scrubbed = sentence[: found.start()] + " " + sentence[found.end() :]
            numbers = [float(t) for t in re.findall(r"\d+(?:\.\d+)?", scrubbed)]
            if all(
                any(_close(m * 100, n) or _close(m, n) for n in numbers) for m in magnitudes
            ):
                return True
    return False


# --- a dataset ---------------------------------------------------------------------------


def _where(recipe: Recipe, spec: DatasetSpec, record: RawRecord) -> str:
    return (
        f"{recipe.path.name} datasets[{spec.index}] "
        f"(ins{record.inspire_id} v{record.version} {spec.table}, column {spec.column})"
    )


def _selected(selector: dict[str, Any], fields: dict[str, Any], table: str) -> bool:
    for name, wanted in selector.items():
        have = table if name == "table" else fields.get(name)
        options = wanted if isinstance(wanted, list) else [wanted]
        if have not in options:
            return False
    return True


def _percent_to_absolute(parsed: Parsed, value: Parsed) -> int | float | None:
    if parsed.value is None or value.value is None:
        return None
    return round_sig(abs(value.value) * parsed.value / 100)


def _error_value(entry: dict[str, Any], value: Parsed) -> tuple[Any, bool]:
    """(the error as it goes in the file, whether it was a percent)."""
    if "symerror" in entry and "asymerror" not in entry:
        parsed = raw.parse_number(entry["symerror"])
        if parsed.percent:
            return _percent_to_absolute(parsed, value), True
        return parsed.value, False
    if "asymerror" in entry and "symerror" not in entry:
        sides = entry["asymerror"]
        if not isinstance(sides, dict) or set(sides) != {"minus", "plus"}:
            raise BuildError(f"asymerror {sides!r} must have 'minus' and 'plus'")
        minus, plus = raw.parse_number(sides["minus"]), raw.parse_number(sides["plus"])
        if minus.percent != plus.percent:
            raise BuildError(f"asymerror {sides!r} mixes a percent and an absolute error")
        if minus.percent:
            return [_percent_to_absolute(minus, value), _percent_to_absolute(plus, value)], True
        return [minus.value, plus.value], False
    raise BuildError(f"error {entry!r} needs exactly one of symerror and asymerror")


def _positions(
    independent: Variable, dependent: Variable
) -> list[dict[str, Any]]:
    if len(independent.values) != len(dependent.values):
        raise BuildError(
            f"{len(independent.values)} x values but {len(dependent.values)} y values"
        )
    bins = []
    for index, cell in enumerate(independent.values):
        entry: dict[str, Any] = {}
        for source, target in (("low", "low"), ("high", "high"), ("value", "centre")):
            if source not in cell:
                continue
            parsed = raw.parse_number(cell[source])
            if parsed.value is None or parsed.percent:
                raise BuildError(f"x point {index}: {source} {cell[source]!r} is not a number")
            entry[target] = parsed.value
        if "low" in entry and entry["low"] == entry.get("high"):
            raise BuildError(f"x point {index}: zero-width bin [{entry['low']}, {entry['high']}]")
        if not entry or ("low" in entry) != ("high" in entry):
            raise BuildError(f"x point {index} has {sorted(cell)}: need low and high, or value")
        bins.append(entry)
    forms = {tuple(sorted(b)) for b in bins}
    if len(forms) != 1:
        raise BuildError(f"the x points mix forms {sorted(forms)}: every point needs the same")
    return bins


def _table_errors(
    dependent: Variable,
    bins: list[dict[str, Any]],
    registry: Registry,
    overrides: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """Fill ``bins`` with the table's error sources; return their declarations."""
    declared: dict[str, dict[str, Any]] = {}
    percent_state: dict[str, bool] = {}
    for index, cell in enumerate(dependent.values):
        value = raw.parse_number(cell.get("value"))
        if value.percent:
            raise BuildError(f"point {index}: the value {cell.get('value')!r} is a percent")
        bins[index]["value"] = value.value
        errors: dict[str, Any] = {}
        for entry in cell.get("errors") or []:
            label = str(entry.get("label", ""))
            name = overrides.get(label) or registry.error_name(label)
            if name is None:
                shown = repr(label) if label else "(no label)"
                raise BuildError(
                    f"error label {shown} has no alias: add it to aliases.yaml, or name the "
                    f"source with `label:` under errors in the recipe"
                )
            if name in errors:
                raise BuildError(f"point {index}: two error labels both mean '{name}'")
            try:
                errors[name], was_percent = _error_value(entry, value)
            except (BuildError, RawError) as exc:
                raise BuildError(f"point {index}, error {label!r}: {exc}") from None
            if percent_state.setdefault(name, was_percent) != was_percent:
                raise BuildError(f"error {label!r} is a percent at some points and not at others")
            declared.setdefault(name, {"label": label, **({"percent": True} if was_percent else {})})
            if declared[name]["label"] != label:
                raise BuildError(
                    f"'{name}' comes from {declared[name]['label']!r} at some points and "
                    f"{label!r} at others"
                )
        if errors:
            bins[index]["errors"] = errors
    return declared


def _additional_values(
    add: Additional, centrality: Any, bins: list[dict[str, Any]], where: str
) -> tuple[list[Any], Any]:
    """The per-bin absolute values of an additional source, and its `relative` field."""
    label = class_label(centrality) if centrality is not None else None
    if add.values is not None:
        if label is None or label not in add.values:
            raise BuildError(f"{where}: additional.{add.name}.values has no class {label!r}")
        given = add.values[label]
        if len(given) != len(bins):
            raise BuildError(
                f"{where}: additional.{add.name}.values[{label!r}] has {len(given)} entries "
                f"but the dataset has {len(bins)} bins"
            )
        return [list(v) if isinstance(v, list) else v for v in given], None

    relative = add.relative
    if isinstance(relative, dict):
        if label is None or label not in relative:
            raise BuildError(
                f"{where}: additional.{add.name}.relative has no class {label!r}; "
                f"restrict it with `for:` if it should not apply here"
            )
        relative = relative[label]
    sides = relative if isinstance(relative, list) else [relative]
    if not all(isinstance(s, (int, float)) and not isinstance(s, bool) for s in sides):
        raise BuildError(f"{where}: additional.{add.name}.relative {relative!r} is not a number")

    def scaled(value: float | None, factor: float) -> float | None:
        return None if value is None else round_sig(abs(value) * factor)

    out: list[Any] = []
    for entry in bins:
        value = entry["value"]
        out.append([scaled(value, s) for s in sides] if isinstance(relative, list) else scaled(value, sides[0]))
    return out, relative


def _apply_additional(
    additional: list[Additional],
    fields: dict[str, Any],
    spec: DatasetSpec,
    table: Table,
    bins: list[dict[str, Any]],
    declared: dict[str, dict[str, Any]],
    where: str,
) -> None:
    added: set[str] = set()
    for add in additional:
        if not _selected(add.selector, fields, spec.table):
            continue
        if add.name in added:
            raise BuildError(
                f"{where}: more than one additional.{add.name} entry applies; narrow their `for:`"
            )
        if add.name in declared:
            raise BuildError(
                f"{where}: additional.{add.name} would replace the table's own source; give "
                f"the paper's value another name"
            )
        added.add(add.name)
        values, relative = _additional_values(add, fields.get("centrality"), bins, where)
        if add.origin == "description" and add.relative is not None:
            magnitudes = [abs(s) for s in (relative if isinstance(relative, list) else [relative])]
            if not description_supports(
                table.description, fields.get("centrality"), magnitudes, add.sample
            ):
                if add.sample is not None:
                    named = f"a line containing {add.sample!r}"
                elif fields.get("centrality") is not None:
                    named = f"a line naming class {class_label(fields['centrality'])}"
                else:
                    named = "a line"
                raise BuildError(
                    f"{where}: additional.{add.name} = {relative!r} is not on {named} in the "
                    f"description of {spec.table}"
                )
        entry: dict[str, Any] = {"origin": add.origin}
        if add.reference:
            entry["reference"] = add.reference
        if add.entered_by:
            entry["entered_by"] = add.entered_by
        if relative is not None:
            entry["relative"] = relative
        if add.note:
            entry["note"] = add.note
        declared[add.name] = entry
        for bin_, value in zip(bins, values):
            bin_.setdefault("errors", {})[add.name] = value


def _build_dataset(
    spec: DatasetSpec,
    recipe: Recipe,
    record: RawRecord,
    registry: Registry,
    schema_document: dict[str, Any],
    inspire: dict[Any, Any],
) -> Built:
    where = _where(recipe, spec, record)
    # A dataset sets a field to null to drop the recipe's default for it.
    fields = {k: v for k, v in spec.fields.items() if v is not None}
    for name in ("observable", "system", "sqrt_s_nn", "experiment", "particle"):
        if name not in fields:
            raise BuildError(f"{where}: '{name}' is not set (neither for the dataset nor the recipe)")
    if fields["observable"] not in registry.observables:
        raise BuildError(
            f"{where}: observable {fields['observable']!r} is not in observables.yaml "
            f"(it has {sorted(registry.observables)})"
        )
    observable = registry.observables[fields["observable"]]
    warnings: list[str] = []

    try:
        table = record.table(spec.table)
        data = table.data
        if spec.column >= len(data.dependent):
            raise BuildError(f"the table has {len(data.dependent)} columns, not {spec.column + 1}")
        dependent = data.dependent[spec.column]
        if len(data.independent) == 1:
            independent = data.independent[0]
        elif spec.x_index is not None and 0 <= spec.x_index < len(data.independent):
            independent = data.independent[spec.x_index]
        else:
            raise BuildError(
                f"the table has {len(data.independent)} independent variables: say which "
                f"with x_index"
            )

        x_name = registry.x_name(independent.name)
        if x_name is None:
            raise BuildError(
                f"the independent variable {independent.name!r} has no alias in aliases.yaml x"
            )
        x_units = registry.unit(independent.units) if independent.units else None
        if x_units is None:
            raise BuildError(
                f"the units {independent.units!r} of the independent variable have no alias "
                f"in aliases.yaml units"
            )

        bins = _positions(independent, dependent)
        overrides = {
            entry["label"]: name for name, entry in recipe.errors.items() if "label" in entry
        }
        declared = _table_errors(dependent, bins, registry, overrides)
        _apply_additional(recipe.additional, fields, spec, table, bins, declared, where)
    except (BuildError, RawError) as exc:
        message = str(exc)
        raise BuildError(message if message.startswith(where) else f"{where}: {message}") from None

    for name, definition in declared.items():
        note = recipe.errors.get(name, {}).get("note")
        if note:
            definition["note"] = note

    error, warning = _centrality_problem(dependent, fields.get("centrality"))
    error = error or _ratio_problem(
        dependent, fields.get("centrality"), fields.get("reference_centrality")
    )
    if error:
        raise BuildError(f"{where}: {error}")
    if warning:
        warnings.append(f"{where}: {warning}")
    warning = _acceptance_warning(dependent, fields.get("acceptance") or {})
    if warning:
        warnings.append(f"{where}: {warning}")
    warnings.extend(
        f"{where}: {w}"
        for w in _identity_warnings(dependent, fields["system"], fields["sqrt_s_nn"])
    )

    dataset: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "observable": fields["observable"],
        "system": fields["system"],
        "sqrt_s_nn": fields["sqrt_s_nn"],
        "experiment": fields["experiment"],
        "particle": fields["particle"],
    }
    for name, definition in registry.fields.items():
        if definition.where == "top" and name in fields:
            dataset[name] = fields[name]
    if fields.get("acceptance"):
        dataset["acceptance"] = fields["acceptance"]

    hepdata: dict[str, Any] = {
        "inspire_id": record.inspire_id,
        "version": record.version,
        "table": table.name,
        "column": spec.column,
    }
    if table.location:
        hepdata["location"] = table.location
    if table.doi:
        hepdata["doi"] = table.doi
    source: dict[str, Any] = {"hepdata": hepdata}
    if recipe.paper:
        source["paper"] = recipe.paper
    if fields.get("figure"):
        source["figure"] = fields["figure"]
    texkey = (inspire.get(record.inspire_id) or {}).get("texkey")
    if texkey:
        source["inspireHEPKey"] = texkey
    dataset["source"] = source
    if fields.get("note"):
        dataset["note"] = fields["note"]

    y: dict[str, Any] = {"name": observable.y}
    if dependent.units:
        y["units"] = dependent.units
    if "definition" in fields:
        y["definition"] = fields["definition"]
    dataset["x"] = {"name": x_name, "units": x_units}
    dataset["y"] = y
    dataset["errors"] = declared
    dataset["bins"] = bins
    dataset["key"] = make_key(dataset, registry)

    problems = schema.schema_problems(dataset, schema_document)
    if not problems:
        problems = schema.semantic_problems(dataset, registry)
    if problems:
        raise BuildError(f"{where}: " + "; ".join(problems))
    return Built(dataset=dataset, recipe=recipe.path, warnings=warnings)


# --- everything --------------------------------------------------------------------------


@dataclass
class BuildResult:
    built: list[Built]
    warnings: list[str]


def load_inspire(root: Path) -> dict[Any, Any]:
    path = root / "inspire.yaml"
    return (yamlio.load(path) if path.exists() else None) or {}


def build_recipes(root: str | Path, registry: Registry, paths: list[Path]) -> BuildResult:
    root = Path(root)
    inspire = load_inspire(root)
    schema_document = schema.dataset_schema(registry)
    built: list[Built] = []
    seen: dict[str, Path] = {}
    for path in paths:
        recipe = recipes.load_recipe(path, registry.fields)
        used: set[str] = set()
        try:
            record = raw.open_record(root, recipe.inspire_id, recipe.version)
        except RawError as exc:
            raise BuildError(f"{path.name}: {exc}") from None
        for spec in recipe.datasets:
            item = _build_dataset(spec, recipe, record, registry, schema_document, inspire)
            if item.key in seen:
                raise BuildError(
                    f"{path.name} datasets[{spec.index}]: key {item.key} is already made by "
                    f"{seen[item.key].name}; add a field that tells them apart to `distinguish` "
                    f"in observables.yaml, or leave one out"
                )
            seen[item.key] = path
            # A recipe can explain a warning that is a quirk of the record, in a comment.
            item.warnings[:] = [
                w for w in item.warnings if not any(k in w for k in recipe.known_warnings)
            ]
            built.append(item)
            used.update(item.dataset["errors"])
        for name in recipe.errors:
            if name not in used:
                built[-1].warnings.append(
                    f"{path.name}: errors.{name} names a source that no dataset has"
                )
    return BuildResult(built=built, warnings=[w for item in built for w in item.warnings])


def render(item: Built) -> str:
    return yamlio.dump_dataset(item.dataset)


def target(root: str | Path, item: Built) -> Path:
    return dataset_path(root, item.dataset)
