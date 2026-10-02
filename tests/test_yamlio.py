import math

import pytest
import yaml

from hsdc import yamlio


@pytest.mark.parametrize(
    "value, text",
    [
        (1.9e-05, "1.9e-05"),
        (1e-05, "1.0e-05"),  # PyYAML reads '1e-05' as a string
        (1e16, "1.0e+16"),
        (0.312275, "0.312275"),
        (250.0, "250.0"),
        (-0.009368, "-0.009368"),
        (5020, "5020"),
        (0, "0"),
    ],
)
def test_number_text_reads_back_as_the_same_number(value, text):
    assert yamlio.number(value) == text
    back = yaml.safe_load(text)
    assert back == value and type(back) is type(value)


def test_nan_and_bool_are_refused():
    with pytest.raises(ValueError):
        yamlio.number(math.nan)
    with pytest.raises(TypeError):
        yamlio.number(True)


@pytest.mark.parametrize(
    "text",
    ["stat", "Table 8", "sys,TAA", "arXiv:1611.01664", "0-5", "yes", "null", "a: b", "#x", "10.5"],
)
def test_strings_read_back_as_the_same_string(text):
    assert yaml.safe_load(f"k: {yamlio.string(text)}")["k"] == text
    assert yaml.safe_load("{ k: " + yamlio.string(text) + " }")["k"] == text


def test_reserved_words_and_numbers_are_quoted():
    for text in ("yes", "No", "NULL", "true", "10.5", "1e5", "0-5"):
        assert yamlio.string(text).startswith('"'), text


def test_flow_of_nested_values():
    value = {"a": 1.5, "b": [1, None, "x y"], "c": {"d": True}}
    assert yaml.safe_load(yamlio.flow(value)) == value


def _dataset(n_errors=3, n_bins=2):
    return {
        "format_version": 1,
        "key": "raa__PbPb5020__CMS__charged__0-5",
        "observable": "raa",
        "system": "PbPb",
        "sqrt_s_nn": 5020,
        "experiment": "CMS",
        "particle": "charged",
        "centrality": [0, 5],
        "acceptance": {"eta_range": [-1.0, 1.0]},
        "source": {"hepdata": {"inspire_id": 1, "version": 2, "table": "Table 8", "column": 0,
                               "doi": "10.1/x"}, "paper": "arXiv:1"},  # fmt: skip
        "note": "a: note, with [brackets] and \"quotes\"",
        "x": {"name": "pt", "units": "GeV"},
        "y": {"name": "raa"},
        "errors": {f"e{i}": {"label": f"label {i}"} for i in range(n_errors)},
        "bins": [
            {
                "low": 1.0 + i,
                "high": 2.0 + i,
                "value": 0.5,
                "errors": {f"e{j}": [-0.001 * j, 0.002 * j] if j % 2 else 1e-05 * j
                           for j in range(n_errors)},  # fmt: skip
            }
            for i in range(n_bins)
        ],
    }


def test_dump_dataset_round_trips():
    dataset = _dataset()
    assert yaml.safe_load(yamlio.dump_dataset(dataset)) == dataset


def test_dump_is_deterministic():
    assert yamlio.dump_dataset(_dataset()) == yamlio.dump_dataset(_dataset())


def test_many_sources_wrap_and_still_parse():
    dataset = _dataset(n_errors=14, n_bins=2)
    text = yamlio.dump_dataset(dataset)
    assert max(len(line) for line in text.splitlines() if line.startswith("      ")) <= 110
    assert yaml.safe_load(text) == dataset


def test_bins_without_errors_or_with_centres():
    dataset = _dataset()
    dataset["bins"] = [{"centre": 1.5, "value": None}, {"centre": 2.5, "value": 0.1}]
    dataset["errors"] = {}
    assert yaml.safe_load(yamlio.dump_dataset(dataset)) == dataset


def test_layout_matches_the_documented_form():
    text = yamlio.dump_dataset(_dataset(n_errors=2, n_bins=1))
    lines = text.splitlines()
    assert lines[0] == "format_version: 1"
    assert lines[1] == "key: raa__PbPb5020__CMS__charged__0-5"
    assert "  - { low: 1.0, high: 2.0, value: 0.5," in lines
    assert any(line.startswith("      errors: { e0: ") for line in lines)
    assert "source:" in lines and "  hepdata:" in lines
