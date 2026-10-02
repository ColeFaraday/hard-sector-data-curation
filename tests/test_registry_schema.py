import copy
import json

import jsonschema
import pytest

from conftest import ALIASES, CENTRALITY, OBSERVABLES, REPO, write
from hsdc import registry as reg
from hsdc import schema


def good_dataset():
    return {
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
            {"low": 1.0, "high": 2.0, "value": 0.5, "errors": {"stat": 0.01, "taa": [-0.1, 0.2]}},
            {"low": 2.0, "high": 3.0, "value": None, "errors": {"stat": None, "taa": [None, 0.1]}},
        ],
    }


def problems(root, dataset):
    registry = reg.load(root)
    found = schema.schema_problems(dataset, schema.dataset_schema(registry))
    return found or schema.semantic_problems(dataset, registry)


# --- registry ----------------------------------------------------------------------------


def test_the_test_registry_loads(root):
    registry = reg.load(root)
    assert registry.error_name("sys,TAA") == "taa" and registry.error_name("zzz") is None
    assert registry.x_name("PT") == "pt" and registry.unit("GEV/c") == "GeV"
    assert registry.observables["vn"].distinguish == ("method", "harmonic", "delta_eta_gap")
    assert registry.centrality["TEST_V0M"].eta_range == ((2.8, 5.1), (-3.7, -1.7))


def test_the_repository_registry_loads():
    registry = reg.load(REPO)
    assert {"raa", "rcp", "vn", "pp_cross_section"} <= set(registry.observables)
    # every final the registry names is a kind CapeTownEloss has
    kinds = {"HADRON_RAA", "HADRON_VN_SP", "HADRON_CROSS_SECTION"}
    for observable in registry.observables.values():
        final = observable.final
        named = set(final["kinds"].values()) if isinstance(final, dict) else {final}
        assert named <= kinds


def test_a_label_under_two_names_is_refused(root):
    write(root / "aliases.yaml", ALIASES.replace('norm: ["norm"]', 'norm: ["stat"]'))
    with pytest.raises(reg.RegistryError, match="'stat' is listed under both"):
        reg.load(root)


def test_bad_registry_entries_are_named(root):
    write(root / "observables.yaml", OBSERVABLES.replace("required: [centrality, centrality_definition]", "required: [centrality, nothing]", 1))
    with pytest.raises(reg.RegistryError, match="'nothing' is not in 'fields'"):
        reg.load(root)
    write(root / "observables.yaml", OBSERVABLES.replace("x: [pt]", "x: [eta]", 1))
    with pytest.raises(reg.RegistryError, match="aliases.yaml"):
        reg.load(root)
    write(root / "observables.yaml", OBSERVABLES.replace('{ harmonic: "n{}", delta_eta_gap: "gap{}" }', '{ method: "m" }'))
    with pytest.raises(reg.RegistryError, match="key_format"):
        reg.load(root)


def test_bad_centrality_definitions_are_named(root):
    write(root / "centrality_definitions.yaml", CENTRALITY.replace("ALICE", "NOBODY", 1))
    with pytest.raises(reg.RegistryError, match="experiment"):
        reg.load(root)
    write(root / "centrality_definitions.yaml", CENTRALITY.replace("[[3.0, 5.0]]", "[[5.0, 3.0]]"))
    with pytest.raises(reg.RegistryError, match="lo < hi"):
        reg.load(root)
    write(root / "centrality_definitions.yaml", CENTRALITY.replace("  reference: \"a paper\"\n", ""))
    with pytest.raises(reg.RegistryError, match="'reference' is required"):
        reg.load(root)


def test_key_and_path(root):
    registry = reg.load(root)
    dataset = good_dataset()
    assert reg.make_key(dataset, registry) == "raa__PbPb5020__CMS__charged__0-5"
    dataset["centrality"] = [0, 0.5]
    dataset["sqrt_s_nn"] = 5023.5
    assert reg.make_key(dataset, registry) == "raa__PbPb5023.5__CMS__charged__0-0.5"
    dataset["key"] = reg.make_key(dataset, registry)
    assert reg.dataset_path("/r", dataset).as_posix() == (
        "/r/curated/raa/PbPb5023.5/raa__PbPb5023.5__CMS__charged__0-0.5.yaml"
    )


def test_final_kind_follows_the_registry(root):
    registry = reg.load(root)
    vn = {"observable": "vn", "method": "SP"}
    assert reg.final_kind(registry.observables["vn"], vn, registry) == "HADRON_VN_SP"
    assert reg.final_kind(registry.observables["vn"], {"method": "EP"}, registry) is None
    assert reg.final_kind(registry.observables["raa"], {}, registry) == "HADRON_RAA"


# --- schema ------------------------------------------------------------------------------


def test_the_generated_schema_is_a_valid_schema(root):
    jsonschema.Draft202012Validator.check_schema(schema.dataset_schema(reg.load(root)))
    jsonschema.Draft202012Validator.check_schema(schema.dataset_schema(reg.load(REPO)))


def test_a_good_dataset_has_no_problems(root):
    assert problems(root, good_dataset()) == []


def test_the_committed_schema_is_what_the_registry_generates():
    registry = reg.load(REPO)
    committed = (REPO / "schema" / "dataset.schema.json").read_text(encoding="utf-8")
    assert committed == schema.schema_text(registry), "run `python -m hsdc schema`"
    assert json.loads(committed)["$id"] == "dataset.schema.json"


@pytest.mark.parametrize(
    "edit, message",
    [
        (lambda d: d.pop("particle"), "'particle' is a required property"),
        (lambda d: d.update(system="pp"), "system"),
        (lambda d: d.update(experiment="NA61"), "experiment"),
        (lambda d: d.update(observable="nonsense"), "observable"),
        (lambda d: d.update(harmonic=2), "harmonic: is not a field of observable raa"),
        (lambda d: d.update(extra=1), "extra"),
        (lambda d: d.update(centrality=[0]), "centrality"),
        (lambda d: d.update(centrality_definition="NOPE"), "centrality_definition"),
        (lambda d: d["x"].update(units="mm"), "x/units"),
        (lambda d: d["x"].update(name="eta"), "x/name"),
        (lambda d: d["y"].update(name="v2"), "y/name"),
        (lambda d: d["acceptance"].update(bad=[0, 1]), "bad"),
        (lambda d: d["errors"].update(bogus={"label": "x"}), "bogus"),
        (lambda d: d["errors"]["stat"].update(origin="paper", reference="x"), "valid under each of"),
        (lambda d: d["errors"].update(taa={"origin": "paper"}), "'reference' is a required property"),
        (lambda d: d["errors"].update(taa={"origin": "manual"}), "'entered_by' is a required property"),
        (lambda d: d["errors"].update(taa={"origin": "unknown", "reference": "x"}), "origin"),
        (lambda d: d["bins"][0].update(value="0.5"), "value"),
        (lambda d: d["bins"][0]["errors"].update(stat=[1, 2, 3]), "stat"),
        (lambda d: d["source"].clear(), "source"),
        (lambda d: d.update(bins=[]), "bins"),
    ],
)
def test_the_schema_rejects(root, edit, message):
    dataset = good_dataset()
    edit(dataset)
    found = problems(root, dataset)
    assert found and any(message in p for p in found), found


@pytest.mark.parametrize(
    "edit, message",
    [
        (lambda d: d.update(key="raa__PbPb5020__CMS__charged__5-10"), "key is"),
        (lambda d: d.update(centrality=[5, 5], key="raa__PbPb5020__CMS__charged__5-5"), "centrality"),
        (lambda d: d.update(centrality=[0, 120], key="raa__PbPb5020__CMS__charged__0-120"), "centrality"),
        (lambda d: d.update(centrality_definition="TEST_V0M"), "belongs to ALICE"),
        (lambda d: d["acceptance"].update(eta_range=[1, -1]), "lo < hi"),
        (lambda d: d["bins"][1].pop("low"), "low and high come together"),
        (lambda d: d["bins"][1].update(low=0.5), "overlap"),
        (lambda d: d["bins"][1].update(low=3.0, high=2.5), "not below high"),
        (lambda d: d["bins"][1].update(centre=2.5), "same form"),
        (lambda d: d["bins"][0]["errors"].update(sys=0.1), "undeclared"),
        (lambda d: d["errors"].update(sys={"label": "sys"}), "never used"),
    ],
)
def test_the_semantic_checks_reject(root, edit, message):
    dataset = copy.deepcopy(good_dataset())
    edit(dataset)
    found = problems(root, dataset)
    assert found and any(message in p for p in found), found


def test_centres_only_datasets_must_increase(root):
    dataset = good_dataset()
    dataset["bins"] = [{"centre": 1.0, "value": 1}, {"centre": 1.0, "value": 2}]
    dataset["errors"] = {}
    assert any("strictly increasing" in p for p in problems(root, dataset))
    dataset["bins"][1]["centre"] = 2.0
    assert problems(root, dataset) == []
