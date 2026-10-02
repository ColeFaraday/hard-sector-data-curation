import pytest

from conftest import (
    BASIC_RECIPE,
    asym,
    bins,
    cell,
    column,
    sym,
    table,
    write_record,
    write_recipe,
)
from hsdc import build as builder
from hsdc import registry as reg
from hsdc import yamlio
from hsdc.build import BuildError


def run(root, tables, recipe=BASIC_RECIPE, **record):
    write_record(root, tables, **record)
    path = write_recipe(root, recipe)
    return builder.build_recipes(root, reg.load(root), [path])


def only(result):
    assert len(result.built) == 1
    return result.built[0].dataset


# --- what a plain table becomes ----------------------------------------------------------


def test_a_table_becomes_one_dataset(root):
    dataset = only(run(root, [table()]))
    assert dataset["key"] == "raa__PbPb5020__CMS__charged__0-5"
    assert dataset["centrality"] == [0, 5]
    assert dataset["centrality_definition"] == "TEST_HF"
    assert dataset["acceptance"] == {"eta_range": [-1.0, 1.0]}
    assert dataset["x"] == {"name": "pt", "units": "GeV"}
    assert dataset["y"] == {"name": "raa"}
    assert dataset["source"]["hepdata"] == {
        "inspire_id": 1001,
        "version": 1,
        "table": "Table 1",
        "column": 0,
        "location": "Data from Fig. 1",
        "doi": "10.17182/hepdata.1001.v1/t1",
    }
    assert dataset["source"]["paper"] == "arXiv:0000.00000"
    assert dataset["errors"] == {"stat": {"label": "stat"}, "sys": {"label": "sys"}}
    assert dataset["bins"][0] == {"low": 5.0, "high": 6.0, "value": 0.5,
                                  "errors": {"stat": 0.01, "sys": 0.02}}  # fmt: skip


def test_the_file_text_is_deterministic(root):
    first = builder.render(run(root, [table()]).built[0])
    second = builder.render(builder.build_recipes(root, reg.load(root), [root / "recipes/ins1001.yaml"]).built[0])
    assert first == second


def test_numbers_and_signs_are_copied_as_they_are(root):
    values = [
        cell(0.31, sym("stat", 1.9e-05), asym("sys", -0.01, 0.02), sym("sys,lumi", -0.007)),
        cell(3, sym("stat", 2), asym("sys", 0.5, -0.25), sym("sys,lumi", 0.0)),
    ]
    dataset = only(run(root, [table(x=bins(2), columns=[column(values=values)])]))
    first, second = dataset["bins"]
    assert first["value"] == 0.31
    assert first["errors"] == {"stat": 1.9e-05, "sys": [-0.01, 0.02], "lumi": -0.007}
    # Nothing is reordered or made positive, and an integer stays an integer.
    assert second["value"] == 3 and isinstance(second["value"], int)
    assert second["errors"]["sys"] == [0.5, -0.25]
    assert isinstance(second["errors"]["stat"], int)


def test_numeric_strings_are_read_and_placeholders_become_null(root):
    values = [
        cell("1.4166e-03", sym("stat", "1.17e-05"), sym("sys", "--")),
        cell("", sym("stat", ""), sym("sys", 0.1)),
    ]
    dataset = only(run(root, [table(x=bins(2), columns=[column(values=values)])]))
    assert dataset["bins"][0]["value"] == 0.0014166
    assert dataset["bins"][0]["errors"] == {"stat": 1.17e-05, "sys": None}
    assert dataset["bins"][1]["value"] is None
    assert dataset["bins"][1]["errors"]["stat"] is None


def test_percent_errors_become_absolute_and_are_flagged(root):
    values = [
        cell(0.5, sym("stat", "2%"), asym("sys", "-4%", "6%")),
        cell(-0.2, sym("stat", "5%"), asym("sys", "-4%", "6%")),
        cell(None, sym("stat", "5%"), asym("sys", "-4%", "6%")),
    ]
    dataset = only(run(root, [table(columns=[column(values=values)])]))
    assert dataset["errors"]["stat"] == {"label": "stat", "percent": True}
    assert dataset["errors"]["sys"] == {"label": "sys", "percent": True}
    one, two, three = dataset["bins"]
    assert one["errors"]["stat"] == pytest.approx(0.01)
    assert one["errors"]["sys"] == pytest.approx([-0.02, 0.03])  # sign of the percent kept
    assert two["errors"]["stat"] == pytest.approx(0.01)  # of |value|
    assert three["errors"]["stat"] is None and three["errors"]["sys"] == [None, None]
    # rounded so that float noise never reaches a file
    assert one["errors"]["stat"] == 0.01


def test_a_source_that_is_percent_at_some_points_only_is_refused(root):
    values = [cell(0.5, sym("stat", "2%")), cell(0.5, sym("stat", 0.01)), cell(0.5, sym("stat", 0.01))]
    with pytest.raises(BuildError, match="percent at some points"):
        run(root, [table(columns=[column(values=values)])])


# --- positions ---------------------------------------------------------------------------


def test_edges_centres_or_both(root):
    edges = only(run(root, [table(x=[{"low": 1, "high": 2}, {"low": 2, "high": 3}], columns=[column(values=column()["values"][:2])])]))
    assert edges["bins"][0]["low"] == 1 and "centre" not in edges["bins"][0]

    centres = only(run(root, [table(x=[{"value": 1.5}, {"value": 2.5}], columns=[column(values=column()["values"][:2])])]))
    assert centres["bins"][0]["centre"] == 1.5 and "low" not in centres["bins"][0]

    both = only(run(root, [table(x=[{"low": 1, "high": 2, "value": 1.4}, {"low": 2, "high": 3, "value": 2.4}],
                                 columns=[column(values=column()["values"][:2])])]))  # fmt: skip
    assert both["bins"][1]["low"] == 2 and both["bins"][1]["centre"] == 2.4


def test_mixed_forms_are_refused(root):
    x = [{"low": 1, "high": 2}, {"value": 2.5}, {"low": 3, "high": 4}]
    with pytest.raises(BuildError, match="mix forms"):
        run(root, [table(x=x)])


@pytest.mark.parametrize(
    "x, message",
    [
        ([{"low": 1, "high": 2}, {"low": 1.5, "high": 2.5}, {"low": 3, "high": 4}], "overlap"),
        ([{"low": 3, "high": 4}, {"low": 2, "high": 3}, {"low": 1, "high": 2}], "overlap or run backwards"),
        ([{"low": 1, "high": 1}, {"low": 2, "high": 3}, {"low": 3, "high": 4}], "zero-width"),
        ([{"low": 2, "high": 1}, {"low": 2, "high": 3}, {"low": 3, "high": 4}], "not below"),
        ([{"value": 3}, {"value": 2}, {"value": 1}], "not strictly increasing"),
        ([{"low": 1}, {"low": 2, "high": 3}, {"low": 3, "high": 4}], "need low and high"),
    ],
)
def test_bad_positions_are_refused(root, x, message):
    with pytest.raises(BuildError, match=message):
        run(root, [table(x=x)])


def test_edges_that_touch_are_fine(root):
    assert only(run(root, [table(x=bins(3))]))  # [5,6] [6,7] [7,8]


# --- labels and vocabulary ---------------------------------------------------------------


def test_an_unknown_label_fails_and_names_the_record_and_table(root):
    values = [cell(0.5, sym("stat", 0.01), sym("sys,new", 0.02))] * 3
    with pytest.raises(BuildError) as raised:
        run(root, [table(columns=[column(values=values)])])
    message = str(raised.value)
    assert "ins1001 v1 Table 1" in message and "'sys,new'" in message and "aliases.yaml" in message


def test_a_recipe_can_name_a_source_for_one_record(root):
    values = [cell(0.5, sym("stat", 0.01), sym("sys,new", 0.02))] * 3
    recipe = BASIC_RECIPE + "errors:\n  norm: { label: \"sys,new\", note: \"what the paper says\" }\n"
    dataset = only(run(root, [table(columns=[column(values=values)])], recipe=recipe))
    assert dataset["errors"]["norm"] == {"label": "sys,new", "note": "what the paper says"}
    assert "norm" in dataset["bins"][0]["errors"]


def test_a_missing_label_can_be_named_by_the_recipe(root):
    values = [cell(0.5, {"symerror": 0.01})] * 3
    with pytest.raises(BuildError, match=r"\(no label\)"):
        run(root, [table(columns=[column(values=values)])])
    recipe = BASIC_RECIPE + 'errors:\n  stat: { label: "" }\n'
    dataset = only(run(root, [table(columns=[column(values=values)])], recipe=recipe))
    assert dataset["errors"]["stat"]["label"] == ""


def test_two_labels_for_one_source_in_a_point_are_refused(root):
    recipe = BASIC_RECIPE + 'errors:\n  stat: { label: "sys" }\n'
    with pytest.raises(BuildError, match="both mean 'stat'"):
        run(root, [table()], recipe=recipe)


def test_notes_on_sources_no_dataset_has_are_reported(root):
    recipe = BASIC_RECIPE + 'errors:\n  lumi: { note: "x" }\n'
    result = run(root, [table()], recipe=recipe)
    assert any("errors.lumi" in w for w in result.warnings)


def test_unknown_independent_variable_or_units(root):
    with pytest.raises(BuildError, match="independent variable 'XX' has no alias"):
        run(root, [table(x_name="XX")])
    with pytest.raises(BuildError, match="units 'KEV'"):
        run(root, [table(x_units="KEV")])
    with pytest.raises(BuildError, match="units None"):
        run(root, [table(x_units=None)])


def test_units_spellings_collapse(root):
    assert only(run(root, [table(x_units="GEV/c")]))["x"]["units"] == "GeV"


# --- the recipe against the table --------------------------------------------------------


@pytest.mark.parametrize("text", ["0-5%", "0-5 pct", "0 - 5 PCT", "0-5", "0\u20135%", "0 to 5"])
def test_the_centrality_qualifier_is_checked_in_every_spelling(root, text):
    tables = [table(columns=[column(qualifiers={"CENTRALITY": text})])]
    assert only(run(root, tables))["centrality"] == [0, 5]


def test_a_wrong_centrality_fails(root):
    tables = [table(columns=[column(qualifiers={"CENT": "5-10 pct"})])]
    with pytest.raises(BuildError, match=r"table says centrality '5-10 pct' but the recipe says \[0, 5\]"):
        run(root, tables)


def test_an_unreadable_centrality_qualifier_is_a_warning(root):
    tables = [table(columns=[column(qualifiers={"CENT": "-"})])]
    assert any("centrality qualifier" in w for w in run(root, tables).warnings)


def test_decimal_classes_do_not_match_by_prefix(root):
    recipe = BASIC_RECIPE.replace("[0, 5]", "[0, 0.5]")
    tables = [table(columns=[column(qualifiers={"CENT": "0-5 pct"})])]
    with pytest.raises(BuildError, match="table says centrality"):
        run(root, tables, recipe=recipe)


def test_an_acceptance_that_disagrees_with_the_table_is_a_warning(root):
    tables = [table(columns=[column(qualifiers={"TRACK ETA": "-0.8 TO 0.8"})])]
    result = run(root, tables)
    assert any("eta_range" in w for w in result.warnings)
    ok = [table(columns=[column(qualifiers={"TRACK ETA": "-1.0 TO 1.0"})])]
    assert not [w for w in run(root, ok).warnings if "eta" in w]


@pytest.mark.parametrize(
    "name, value, acceptance, warns",
    [
        ("ABS(ETA)", "0.0-2.5", "{ eta_range: [-2.5, 2.5] }", False),
        ("ABS(ETA)", "0.0-2.5", "{ eta_range: [-2.0, 2.0] }", True),
        ("ABS(ETA)", "0.25-0.50", "{ abs_eta_range: [0.25, 0.5] }", False),
        ("ABS(ETA)", "0.25-0.50", "{ eta_range: [-0.5, 0.5] }", True),  # that is a different window
        ("ABS(ETA)", "0.25-0.50", "{ abs_eta_range: [0.25, 0.6] }", True),
        ("$|\\eta|$", "< 1", "{ eta_range: [-1.0, 1.0] }", False),
        ("ETARAP", "-0.3 - 1.3", "{ eta_range: [-0.3, 1.3] }", False),
        ("Y*", "-2.5-2.0", "{ y_range: [-2.5, 2.0] }", False),
        ("Y*", "-2.5-2.0", "{ y_range: [-2.5, 2.5] }", True),
        ("Y*", "-2.5-2.0", "{ eta_range: [-2.5, 2.0] }", True),
    ],
)
def test_the_eta_and_rapidity_windows_are_compared_the_way_they_are_written(root, name, value, acceptance, warns):
    recipe = BASIC_RECIPE.replace("acceptance: { eta_range: [-1.0, 1.0] }", f"acceptance: {acceptance}")
    result = run(root, [table(columns=[column(qualifiers={name: value})])], recipe=recipe)
    assert bool([w for w in result.warnings if "table gives" in w]) == warns, result.warnings


def test_column_and_table_selection(root):
    columns = [column(values=[cell(v, sym("stat", 0.1), sym("sys", 0.1))] * 3) for v in (0.1, 0.2, 0.3)]
    tables = [table("Table 1"), table("Table 2", columns=columns)]
    recipe = BASIC_RECIPE.replace(
        "table: Table 1,", "table: Table 2, column: 2,"
    )
    dataset = only(run(root, tables, recipe=recipe))
    assert dataset["bins"][0]["value"] == 0.3
    assert dataset["source"]["hepdata"]["table"] == "Table 2"
    assert dataset["source"]["hepdata"]["column"] == 2


def test_a_missing_column_or_table_is_refused(root):
    with pytest.raises(BuildError, match="1 columns, not 4"):
        run(root, [table()], recipe=BASIC_RECIPE.replace("table: Table 1,", "table: Table 1, column: 3,"))
    with pytest.raises(BuildError, match="no table 'Table 7'"):
        run(root, [table()], recipe=BASIC_RECIPE.replace("Table 1", "Table 7"))


def test_two_independent_variables_need_x_index(root):
    spec = table()
    spec["x"].append({"header": {"name": "PT", "units": "GEV"}, "values": bins()})
    with pytest.raises(BuildError, match="x_index"):
        run(root, [spec])
    recipe = BASIC_RECIPE.replace("table: Table 1,", "table: Table 1, x_index: 1,")
    assert only(run(root, [spec], recipe=recipe))


def test_dataset_fields_override_the_recipe_and_acceptance_merges(root):
    recipe = """
    record: { inspire_id: 1001, version: 1 }
    experiment: CMS
    particle: charged
    sqrt_s_nn: 5020
    centrality_definition: TEST_HF
    acceptance: { eta_range: [-1.0, 1.0] }
    datasets:
      - { table: Table 1, observable: raa, system: PbPb, centrality: [0, 5], note: "mine",
          acceptance: { delta_eta_gap: 2 } }
    """
    dataset = only(run(root, [table()], recipe=recipe))
    assert dataset["acceptance"] == {"eta_range": [-1.0, 1.0], "delta_eta_gap": 2}
    assert dataset["note"] == "mine"


def test_missing_required_metadata_is_named(root):
    recipe = BASIC_RECIPE.replace("experiment: CMS\n", "")
    with pytest.raises(BuildError, match="'experiment' is not set"):
        run(root, [table()], recipe=recipe)


# --- the format --------------------------------------------------------------------------


def test_a_missing_centrality_definition_fails(root):
    recipe = BASIC_RECIPE.replace("TEST_HF", "NOT_THERE")
    with pytest.raises(BuildError, match="centrality_definition"):
        run(root, [table()], recipe=recipe)


def test_a_definition_of_another_experiment_fails(root):
    recipe = BASIC_RECIPE.replace("TEST_HF", "TEST_V0M")
    with pytest.raises(BuildError, match="belongs to ALICE, not CMS"):
        run(root, [table()], recipe=recipe)


def test_fields_an_observable_does_not_take_are_refused(root):
    recipe = BASIC_RECIPE.replace("centrality: [0, 5]", "centrality: [0, 5], harmonic: 2")
    with pytest.raises(BuildError, match="harmonic"):
        run(root, [table()], recipe=recipe)


def test_required_fields_are_enforced(root):
    recipe = BASIC_RECIPE.replace("observable: raa", "observable: vn, harmonic: 2")
    with pytest.raises(BuildError, match="method"):
        run(root, [table()], recipe=recipe)


def test_unknown_observable_lists_the_known_ones(root):
    with pytest.raises(BuildError, match="observable 'foo'.*raa"):
        run(root, [table()], recipe=BASIC_RECIPE.replace("observable: raa", "observable: foo"))


def test_the_system_has_to_suit_the_observable(root):
    with pytest.raises(BuildError, match="system"):
        run(root, [table()], recipe=BASIC_RECIPE.replace("system: PbPb", "system: pp"))


def test_distinguishing_fields_extend_the_key(root):
    recipe = """
    record: { inspire_id: 1001, version: 1 }
    experiment: ALICE
    particle: charged
    sqrt_s_nn: 5020
    system: PbPb
    observable: vn
    harmonic: 2
    centrality_definition: TEST_V0M
    datasets:
      - { table: Table 1, method: SP, centrality: [20, 30] }
      - { table: Table 1, method: cumulant2, centrality: [20, 30], acceptance: { delta_eta_gap: 1.5 } }
    """
    result = run(root, [table()], recipe=recipe)
    assert [b.key for b in result.built] == [
        "vn__PbPb5020__ALICE__charged__20-30__SP__n2",
        "vn__PbPb5020__ALICE__charged__20-30__cumulant2__n2__gap1.5",
    ]


def test_two_datasets_with_one_key_fail_and_say_how_to_tell_them_apart(root):
    recipe = BASIC_RECIPE + "  - { table: Table 1, observable: raa, system: PbPb, centrality: [0, 5] }\n"
    with pytest.raises(BuildError, match="already made.*distinguish"):
        run(root, [table()], recipe=recipe)


def test_spectra_carry_their_definition_and_units(root):
    recipe = """
    record: { inspire_id: 1001, version: 1 }
    experiment: CMS
    particle: charged
    sqrt_s_nn: 5020
    system: pp
    observable: pp_cross_section
    definition: INVARIANT_YIELD_DETA
    datasets:
      - { table: Table 1 }
    """
    spec = table(columns=[column(name="(1/N)*E*D3(N)/DP(3)", units="GEV**-2")])
    dataset = only(run(root, [spec], recipe=recipe))
    assert dataset["y"] == {"name": "cross_section", "units": "GEV**-2",
                            "definition": "INVARIANT_YIELD_DETA"}  # fmt: skip
    assert dataset["key"] == "pp_cross_section__pp5020__CMS__charged__INVARIANT_YIELD_DETA"
    assert "centrality" not in dataset


def test_a_spectrum_without_a_definition_fails(root):
    recipe = """
    record: { inspire_id: 1001, version: 1 }
    experiment: CMS
    particle: charged
    sqrt_s_nn: 5020
    system: pp
    observable: pp_cross_section
    datasets:
      - { table: Table 1 }
    """
    with pytest.raises(BuildError, match="definition"):
        run(root, [table()], recipe=recipe)


# --- values typed in from a description or the paper -------------------------------------

ALICE_LIKE = """
record: { inspire_id: 1001, version: 1 }
experiment: ALICE
particle: charged
sqrt_s_nn: 5020
system: PbPb
observable: raa
centrality_definition: TEST_V0M
datasets:
  - { table: Table 1, column: 0, centrality: [0, 5] }
  - { table: Table 1, column: 1, centrality: [5, 10] }
additional:
  norm:
    origin: description
    relative: { "0-5": [-0.027, 0.027], "5-10": 0.035 }
    note: "T_AA and pp normalisation"
"""

DESCRIPTION = (
    "Additional systematic error for PBPB 0-5 pct data: +2.7 pct -2.7 pct\n"
    "Additional systematic error for PBPB 5-10 pct data: +3.5 pct -3.5 pct.\n"
)


def _two_classes():
    return table(
        description=DESCRIPTION,
        columns=[
            column(qualifiers={"CENT": "0-5 pct"}),
            column(values=[cell(1.0, sym("stat", 0.1), sym("sys", 0.1))] * 3,
                   qualifiers={"CENT": "5-10 pct"}),  # fmt: skip
        ],
    )


def test_a_description_value_is_added_per_class_and_checked_against_the_text(root):
    result = run(root, [_two_classes()], recipe=ALICE_LIKE)
    first, second = (b.dataset for b in result.built)
    assert first["errors"]["norm"] == {
        "origin": "description",
        "relative": [-0.027, 0.027],
        "note": "T_AA and pp normalisation",
    }
    assert first["bins"][0]["errors"]["norm"] == pytest.approx([0.5 * -0.027, 0.5 * 0.027])
    assert second["errors"]["norm"]["relative"] == 0.035
    assert second["bins"][0]["errors"]["norm"] == pytest.approx(0.035)
    assert list(first["errors"]) == ["stat", "sys", "norm"]  # the table's sources, then the typed ones


def test_a_description_value_on_the_wrong_class_line_fails(root):
    swapped = ALICE_LIKE.replace('"0-5": [-0.027, 0.027], "5-10": 0.035', '"0-5": 0.035, "5-10": [-0.027, 0.027]')
    with pytest.raises(BuildError, match="not on a line naming class 0-5"):
        run(root, [_two_classes()], recipe=swapped)


def test_a_description_value_that_is_not_in_the_text_fails(root):
    wrong = ALICE_LIKE.replace("0.035", "0.036")
    with pytest.raises(BuildError, match="5-10"):
        run(root, [_two_classes()], recipe=wrong)


def test_class_edges_are_not_mistaken_for_the_value(root):
    # '0-5' contains a 5; a recipe value of 5 per cent must not be satisfied by the class name.
    spec = table(description="PBPB 0-5 pct data: +2.7 pct", columns=[column(qualifiers={"CENT": "0-5 pct"})])
    recipe = ALICE_LIKE.replace('"0-5": [-0.027, 0.027], "5-10": 0.035', '"0-5": 0.05').replace(
        "  - { table: Table 1, column: 1, centrality: [5, 10] }\n", ""
    )
    with pytest.raises(BuildError, match="not on a line naming class 0-5"):
        run(root, [spec], recipe=recipe)


def test_a_class_map_needs_every_class_or_a_selector(root):
    missing = ALICE_LIKE.replace(', "5-10": 0.035', "")
    with pytest.raises(BuildError, match="no class '5-10'.*for:"):
        run(root, [_two_classes()], recipe=missing)


def test_a_selector_limits_where_a_source_applies(root):
    recipe = ALICE_LIKE.replace("origin: description\n", "origin: description\n    for: { centrality_definition: OTHER }\n")
    result = run(root, [_two_classes()], recipe=recipe)
    assert all("norm" not in b.dataset["errors"] for b in result.built)


def test_paper_values_need_a_reference_and_manual_ones_a_name(root):
    base = ALICE_LIKE.replace("origin: description", "origin: paper")
    with pytest.raises(Exception, match="reference"):
        run(root, [_two_classes()], recipe=base)
    paper = base.replace("origin: paper", 'origin: paper\n    reference: "Sec. 4, Table 2"')
    result = run(root, [_two_classes()], recipe=paper)
    assert result.built[0].dataset["errors"]["norm"]["reference"] == "Sec. 4, Table 2"
    manual = ALICE_LIKE.replace("origin: description", "origin: manual")
    with pytest.raises(Exception, match="entered_by"):
        run(root, [_two_classes()], recipe=manual)


def test_a_paper_value_never_replaces_a_table_source(root):
    recipe = ALICE_LIKE.replace("  norm:", "  stat:")
    with pytest.raises(BuildError, match="would replace the table's own source"):
        run(root, [_two_classes()], recipe=recipe)


def test_per_bin_values_are_copied(root):
    recipe = """
    record: { inspire_id: 1001, version: 1 }
    experiment: ALICE
    particle: charged
    sqrt_s_nn: 5020
    system: PbPb
    observable: raa
    centrality_definition: TEST_V0M
    datasets:
      - { table: Table 1, centrality: [0, 5] }
    additional:
      taa:
        origin: paper
        reference: "Table 3"
        values: { "0-5": [0.01, [-0.01, 0.02], null] }
    """
    dataset = only(run(root, [table()], recipe=recipe))
    assert [b["errors"]["taa"] for b in dataset["bins"]] == [0.01, [-0.01, 0.02], None]
    assert "relative" not in dataset["errors"]["taa"]
    bad = recipe.replace("[0.01, [-0.01, 0.02], null]", "[0.01]")
    with pytest.raises(BuildError, match="1 entries but the dataset has 3 bins"):
        run(root, [table()], recipe=bad)


def test_every_dataset_passes_the_schema_and_round_trips(root):
    result = run(root, [_two_classes()], recipe=ALICE_LIKE)
    for item in result.built:
        assert yamlio.loads(builder.render(item)) == item.dataset


MINIMUM_BIAS = """
record: { inspire_id: 1001, version: 1 }
experiment: ALICE
particle: charged
sqrt_s_nn: 5020
system: pPb
observable: raa
centrality_definition: TEST_V0M
datasets:
  - { table: Table 1, centrality: [0, 100] }
additional:
  norm:
    origin: description
    sample: "P-PB NSD"
    relative: [-0.046, 0.046]
"""


def test_a_minimum_bias_value_is_found_by_the_name_of_the_sample(root):
    spec = table(description="Additional systematic error for P-PB NSD data: +4.6 pct -4.6 pct.\n")
    dataset = only(run(root, [spec], recipe=MINIMUM_BIAS))
    assert dataset["errors"]["norm"]["relative"] == [-0.046, 0.046]


def test_the_sample_name_has_to_be_on_the_same_line_as_the_number(root):
    spec = table(description="P-PB NSD data.\nAdditional systematic error: +4.6 pct -4.6 pct.\n")
    with pytest.raises(BuildError, match="a line containing 'P-PB NSD'"):
        run(root, [spec], recipe=MINIMUM_BIAS)
    other = table(description="Additional systematic error for P-PB NSD data: +9.9 pct -9.9 pct.\n")
    with pytest.raises(BuildError, match="a line containing 'P-PB NSD'"):
        run(root, [other], recipe=MINIMUM_BIAS)


def test_a_minimum_bias_class_needs_a_sample_because_the_text_never_says_0_100(root):
    spec = table(description="Additional systematic error for P-PB NSD data: +4.6 pct -4.6 pct.\n")
    with pytest.raises(BuildError, match="a line naming class 0-100"):
        run(root, [spec], recipe=MINIMUM_BIAS.replace('    sample: "P-PB NSD"\n', ""))


def test_a_key_yaml_reads_as_a_boolean_is_explained(root):
    recipe = ALICE_LIKE.replace("    origin: description\n", "    origin: description\n    on: x\n")
    with pytest.raises(Exception, match=r"the key True is not text.*quotes"):
        run(root, [_two_classes()], recipe=recipe)


def test_one_source_can_have_an_entry_per_table(root):
    recipe = """
    record: { inspire_id: 1001, version: 1 }
    experiment: ALICE
    particle: charged
    sqrt_s_nn: 5020
    system: PbPb
    observable: raa
    centrality_definition: TEST_V0M
    datasets:
      - { table: Table 1, centrality: [0, 5] }
      - { table: Table 2, centrality: [0, 5], sqrt_s_nn: 2760 }
    additional:
      norm:
        - { origin: description, for: { table: Table 1 }, relative: { "0-5": 0.027 } }
        - { origin: description, for: { table: Table 2 }, relative: { "0-5": 0.022 } }
    """
    one = table(description="PBPB 0-5 pct data: +2.7 pct -2.7 pct")
    two = table("Table 2", description="PBPB 0-5 pct data: +2.2 pct -2.2 pct")
    first, second = (b.dataset for b in run(root, [one, two], recipe=recipe).built)
    assert first["errors"]["norm"]["relative"] == 0.027
    assert second["errors"]["norm"]["relative"] == 0.022


def test_two_entries_that_both_apply_are_refused(root):
    recipe = """
    record: { inspire_id: 1001, version: 1 }
    experiment: ALICE
    particle: charged
    sqrt_s_nn: 5020
    system: PbPb
    observable: raa
    centrality_definition: TEST_V0M
    datasets:
      - { table: Table 1, centrality: [0, 5] }
    additional:
      norm:
        - { origin: description, relative: { "0-5": 0.027 } }
        - { origin: description, relative: { "0-5": 0.027 } }
    """
    with pytest.raises(BuildError, match="more than one additional.norm entry applies"):
        run(root, [table(description="PBPB 0-5 pct data: +2.7 pct")], recipe=recipe)


RCP_RECIPE = """
record: { inspire_id: 1001, version: 1 }
experiment: CMS
particle: charged
sqrt_s_nn: 2760
system: PbPb
observable: rcp
centrality_definition: TEST_HF
datasets:
  - { table: Table 1, column: 0, centrality: [0, 5], reference_centrality: [50, 90] }
  - { table: Table 1, column: 1, centrality: [5, 10], reference_centrality: [50, 90] }
"""


def _ratio_table(*texts):
    return table(columns=[column(name="RCP", qualifiers={"": t}) for t in texts])


def test_the_classes_of_a_ratio_are_checked_from_an_unnamed_qualifier(root):
    result = run(root, [_ratio_table("0-5%/50-90%", "5-10%/50-90%")], recipe=RCP_RECIPE)
    first, second = (b.dataset for b in result.built)
    assert first["key"] == "rcp__PbPb2760__CMS__charged__0-5"
    assert first["reference_centrality"] == [50, 90] and second["centrality"] == [5, 10]


@pytest.mark.parametrize("second", ["10-30%/50-90%", "5-10%/60-80%"])
def test_a_ratio_with_the_wrong_class_or_reference_fails(root, second):
    with pytest.raises(BuildError, match="the table says the ratio"):
        run(root, [_ratio_table("0-5%/50-90%", second)], recipe=RCP_RECIPE)


def test_a_null_drops_a_recipe_default_for_one_dataset(root):
    recipe = """
    record: { inspire_id: 1001, version: 1 }
    experiment: CMS
    particle: charged
    sqrt_s_nn: 5020
    centrality_definition: TEST_HF
    datasets:
      - { table: Table 1, observable: raa, system: PbPb, centrality: [0, 5] }
      - { table: Table 1, observable: pp_cross_section, system: pp, definition: INVARIANT_YIELD_DETA, centrality_definition: null }
    """
    result = run(root, [table(columns=[column(units="GEV**-2")])], recipe=recipe)
    assert "centrality_definition" in result.built[0].dataset
    assert "centrality_definition" not in result.built[1].dataset


def test_a_variant_tells_datasets_apart_and_ends_the_key(root):
    recipe = BASIC_RECIPE.replace(
        "datasets:\n", "datasets:\n  - { table: Table 1, observable: raa, system: PbPb, centrality: [0, 5], variant: abseta0.5-1, acceptance: { abs_eta_range: [0.5, 1.0] } }\n"
    )
    result = run(root, [table()], recipe=recipe)
    assert [b.key for b in result.built] == [
        "raa__PbPb5020__CMS__charged__0-5__abseta0.5-1",
        "raa__PbPb5020__CMS__charged__0-5",
    ]
    assert result.built[0].dataset["variant"] == "abseta0.5-1"
    assert result.built[0].dataset["acceptance"] == {"eta_range": [-1.0, 1.0], "abs_eta_range": [0.5, 1.0]}


def test_a_variant_has_to_be_a_token(root):
    recipe = BASIC_RECIPE.replace("centrality: [0, 5] }", "centrality: [0, 5], variant: a_b }")
    with pytest.raises(BuildError, match="variant"):
        run(root, [table()], recipe=recipe)


def test_a_field_the_registry_does_not_have_is_refused_by_name(root):
    recipe = BASIC_RECIPE.replace("centrality: [0, 5] }", "centrality: [0, 5], flavour: up }")
    with pytest.raises(Exception, match=r"unknown keys \['flavour'\]"):
        run(root, [table()], recipe=recipe)


@pytest.mark.parametrize(
    "text, window",
    [
        ("-1.0 TO 1.0", (-1.0, 1.0)),
        ("-0.8 - 0.8", (-0.8, 0.8)),
        ("-2.5-2.0", (-2.5, 2.0)),
        ("< 1", (-1.0, 1.0)),
        ("< 0.8 (LAB)", (-0.8, 0.8)),
        ("0.0-2.5 (abs)", (0.0, 2.5)),
        ("forward", None),
    ],
)
def test_parse_window(text, window):
    assert builder.parse_window(text) == window


def test_a_table_that_names_another_system_or_energy_is_a_warning(root):
    wrong_system = table(columns=[column(qualifiers={"RE": "P P --> CHARGED X"})])
    assert any("reaction" in w and "says PbPb" in w for w in run(root, [wrong_system]).warnings)
    right = table(columns=[column(qualifiers={"RE": "PB PB --> CHARGED X", "SQRT(S)/NUCLEON": "5020.0"})])
    assert not run(root, [right]).warnings
    for text in ("5.02 TeV", "5020.0 GeV", "5020"):
        assert not [w for w in run(root, [table(columns=[column(qualifiers={"SQRT(S)": text})])]).warnings if "SQRT" in w]
    wrong_energy = table(columns=[column(qualifiers={"SQRT(S)/NUCLEON": "2760.0"})])
    assert any("SQRT(S)/NUCLEON is '2760.0'" in w for w in run(root, [wrong_energy]).warnings)


def test_a_known_warning_is_explained_by_the_recipe(root):
    quirk = table(columns=[column(qualifiers={"RE": "P P --> CHARGED X"})])
    recipe = BASIC_RECIPE + "known_warnings:\n  - \"reaction is 'P P --> CHARGED X'\"\n"
    assert run(root, [quirk], recipe=recipe).warnings == []
    other = table(columns=[column(qualifiers={"RE": "PB PB --> CHARGED X", "SQRT(S)": "2760"})])
    assert run(root, [other], recipe=recipe).warnings  # only what it names is explained
