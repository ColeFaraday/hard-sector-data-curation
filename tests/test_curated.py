"""The committed datasets against the recipes, the schema and the raw HEPData files."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from conftest import REPO
from hsdc import build as builder
from hsdc import reader
from hsdc import registry as reg
from hsdc import schema, yamlio

RECIPES = sorted((REPO / "recipes").glob("*.yaml"))
CURATED = sorted((REPO / "curated").rglob("*.yaml"))
Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


@pytest.fixture(scope="module")
def registry():
    return reg.load(REPO)


@pytest.fixture(scope="module")
def rebuilt(registry):
    result = builder.build_recipes(REPO, registry, RECIPES)
    return {builder.target(REPO, item): builder.render(item) for item in result.built}


def test_every_recipe_builds_and_curated_is_exactly_that(rebuilt):
    """The committed files are what the recipes make now, byte for byte, and nothing else."""
    assert set(rebuilt) == set(CURATED), "run `python -m hsdc build`"
    for path, text in rebuilt.items():
        assert path.read_text(encoding="utf-8") == text, f"{path.name} is out of date"


def test_every_file_passes_the_schema(registry):
    document = schema.dataset_schema(registry)
    for path in CURATED:
        data = yamlio.load(path)
        assert schema.schema_problems(data, document) == [], path.name
        assert schema.semantic_problems(data, registry) == [], path.name
        assert reg.dataset_path(REPO, data) == path


def test_keys_are_unique_and_files_are_named_by_key():
    keys = [yamlio.load(p)["key"] for p in CURATED]
    assert len(keys) == len(set(keys))
    assert [p.stem for p in CURATED] == [yamlio.load(p)["key"] for p in CURATED]


def test_the_registry_names_the_papers_inspire_key():
    keys = yamlio.load(REPO / "inspire.yaml")
    for path in CURATED:
        source = yamlio.load(path)["source"]
        if "hepdata" in source:
            assert source["inspireHEPKey"] == keys[source["hepdata"]["inspire_id"]]["texkey"]


# --- the numbers, against the raw files read a second way --------------------------------


def _number(cell):
    """What a HEPData cell is, read with no help from hsdc."""
    if cell is None or (isinstance(cell, str) and cell.strip() in ("", "--", "-")):
        return None
    if isinstance(cell, str):
        return float(cell.strip().rstrip("%"))
    return cell


def _raw_column(hepdata):
    matches = sorted(
        (REPO / "data").glob(f"**/HEPData-ins{hepdata['inspire_id']}-v{hepdata['version']}-yaml")
    )
    assert matches, hepdata
    folder = matches[0]
    documents = list(yaml.load_all((folder / "submission.yaml").read_text(), Loader=Loader))
    entry = next(t for t in documents[1:] if t["name"] == hepdata["table"])
    data = yaml.load((folder / entry["data_file"]).read_text(), Loader=Loader)
    return data["independent_variables"], data["dependent_variables"][hepdata["column"]]


def _same_bins(independent, dataset):
    for variable in independent:
        cells = variable["values"]
        if len(cells) != len(dataset["bins"]):
            continue
        ok = True
        for cell, entry in zip(cells, dataset["bins"]):
            for raw_key, key in (("low", "low"), ("high", "high"), ("value", "centre")):
                if (raw_key in cell) != (key in entry) or (
                    key in entry and _number(cell[raw_key]) != entry[key]
                ):
                    ok = False
        if ok:
            return True
    return False


@pytest.mark.parametrize("path", CURATED, ids=lambda p: p.stem)
def test_numbers_are_the_raw_numbers(path):
    dataset = yamlio.load(path)
    hepdata = dataset["source"]["hepdata"]
    independent, column = _raw_column(hepdata)

    assert _same_bins(independent, dataset), "the bin positions differ from the raw table"
    assert len(column["values"]) == len(dataset["bins"])
    labelled = {
        name: definition["label"]
        for name, definition in dataset["errors"].items()
        if "label" in definition
    }
    for index, (cell, entry) in enumerate(zip(column["values"], dataset["bins"])):
        where = f"{path.stem} bin {index}"
        value = _number(cell.get("value"))
        assert entry["value"] == value, where
        raw_errors = {e.get("label", ""): e for e in cell.get("errors", [])}
        expected_names = {name for name, label in labelled.items() if label in raw_errors}
        assert set(entry.get("errors", {})) - expected_names == {
            n for n, d in dataset["errors"].items() if "origin" in d
        } & set(entry.get("errors", {})), where
        for name in expected_names:
            raw = raw_errors[labelled[name]]
            percent = dataset["errors"][name].get("percent", False)
            if "symerror" in raw:
                want = _number(raw["symerror"])
                if percent:
                    want = None if want is None or value is None else abs(value) * want / 100
            else:
                want = [_number(raw["asymerror"]["minus"]), _number(raw["asymerror"]["plus"])]
                if percent:
                    want = [None if w is None or value is None else abs(value) * w / 100 for w in want]
            got = entry["errors"][name]
            if percent and want is not None:
                assert got == pytest.approx(want, rel=1e-9), where
            else:
                assert got == want, where
