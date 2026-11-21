"""The format check and the vocabulary's keys and finals."""

import copy

import pytest

from hsdc import check, vocab


def dataset(**changes):
    base = {
        "format_version": 1,
        "key": "raa__PbPb5020__CMS__charged__0-5",
        "observable": "raa",
        "system": "PbPb",
        "sqrt_s_nn": 5020,
        "experiment": "CMS",
        "particle": "charged",
        "centrality": [0, 5],
        "centrality_definition": "TEST_HF",
        "acceptance": {"eta_range": [-1.0, 1.0]},
        "source": {"hepdata": {"inspire_id": 1, "version": 1, "table": "Table 1", "column": 0}},
        "x": {"name": "pt", "units": "GeV"},
        "y": {"name": "raa"},
        "errors": {"stat": {"label": "stat"}, "taa": {"label": "sys,TAA"}},
        "bins": [
            {"low": 5.0, "high": 6.0, "value": 0.2, "errors": {"stat": 0.01, "taa": [-0.01, 0.02]}},
            {"low": 6.0, "high": 8.0, "value": None, "errors": {"stat": None}},
        ],
    }
    out = copy.deepcopy(base)
    out.update(changes)
    return out


def test_a_good_dataset_has_no_problems(root):
    assert check.problems(dataset(), root) == []


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"harmonic": 2}, "harmonic is not a field of observable raa"),
        ({"acceptance": {"delta_eta_gap": 1.0}}, "delta_eta_gap is not a field"),
        ({"system": "pp"}, "system 'pp'"),
        ({"centrality": [5, 0]}, "lo < hi"),
        ({"centrality": [50, 120]}, "[0, 100]"),
        ({"centrality_definition": "NOPE"}, "not in centrality_definitions.yaml"),
        ({"centrality_definition": "TEST_V0M"}, "belongs to ALICE, not CMS"),
        ({"variant": "a_b"}, "variant 'a_b'"),
        ({"y": {"name": "vn"}}, "y.name must be 'raa'"),
        ({"x": {"name": "pt", "units": "furlongs"}}, "x must be"),
        ({"errors": {"stat": {"label": "stat"}}}, "undeclared error sources ['taa']"),
        ({"errors": {"stat": {"label": "stat"}, "taa": {"label": "x"}, "lumi": {"origin": "manual", "entered_by": "me"}}},
         "never used by a bin: ['lumi']"),
        ({"errors": {"stat": {"label": "stat"}, "taa": {"origin": "paper"}}}, "needs a reference"),
        ({"errors": {"stat": {"label": "stat"}, "taa": {"label": "x", "origin": "manual"}}}, "not both"),
        ({"errors": {"stat": {"label": "stat"}, "taa": {"label": "x"}, "bogus": {"label": "y"}}}, "'bogus' is not a name"),
        ({"key": "raa__PbPb5020__CMS__charged__0-10"}, "its fields make"),
        ({"source": {"note": "x"}}, "source needs"),
        ({"observable": "foo"}, "observable 'foo'"),
    ],
)
def test_problems_are_named(root, changes, message):
    found = check.problems(dataset(**changes), root)
    assert any(message in p for p in found), found


def test_bins_must_be_in_order_and_of_one_form(root):
    overlapping = dataset()
    overlapping["bins"][1]["low"] = 5.5
    assert any("overlap" in p for p in check.problems(overlapping, root))
    mixed = dataset()
    mixed["bins"][1] = {"centre": 7.0, "value": 0.3, "errors": {"stat": 0.01}}
    assert any("same form" in p for p in check.problems(mixed, root))
    bad_error = dataset()
    bad_error["bins"][0]["errors"]["stat"] = [0.1]
    assert any("[minus, plus]" in p for p in check.problems(bad_error, root))


def test_keys_follow_the_distinguishing_fields():
    vn = {"observable": "vn", "system": "PbPb", "sqrt_s_nn": 5020, "experiment": "ATLAS",
          "particle": "charged", "centrality": [20, 30], "method": "SP", "harmonic": 3,
          "acceptance": {"delta_eta_gap": 2.0}}  # fmt: skip
    assert vocab.make_key(vn) == "vn__PbPb5020__ATLAS__charged__20-30__SP__n3__gap2"
    pp = {"observable": "pp_cross_section", "system": "pp", "sqrt_s_nn": 5020, "experiment": "CMS",
          "particle": "charged", "y": {"definition": "INVARIANT_CROSS_SECTION_DETA"}, "variant": "x"}  # fmt: skip
    assert vocab.make_key(pp) == "pp_cross_section__pp5020__CMS__charged__INVARIANT_CROSS_SECTION_DETA__x"


@pytest.mark.parametrize(
    "fields, final",
    [
        ({"observable": "raa"}, "HADRON_RAA"),
        ({"observable": "rcp"}, "HADRON_RAA"),
        ({"observable": "vn", "method": "SP"}, "HADRON_VN_SP"),
        ({"observable": "vn", "method": "cumulant2"}, None),
        ({"observable": "pp_cross_section", "y": {"definition": "CROSS_SECTION_DPT_DETA"}}, "HADRON_CROSS_SECTION"),
        ({"observable": "pp_cross_section", "y": {"definition": "INVARIANT_YIELD_DETA"}}, None),
    ],
)
def test_final_kind(fields, final):
    assert vocab.final_kind(fields) == final


def test_an_alias_under_two_names_is_refused(tmp_path):
    (tmp_path / "aliases.yaml").write_text('errors:\n  a: ["x"]\n  b: ["x"]\n')
    with pytest.raises(vocab.VocabularyError, match="under both"):
        vocab.aliases(tmp_path)
