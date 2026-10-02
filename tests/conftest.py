"""A throw-away data repository: a small registry, and synthetic HEPData records."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]

ALIASES = """
errors:
  stat: ["stat"]
  sys: ["sys"]
  taa: ["sys,TAA"]
  lumi: ["sys,lumi"]
  norm: ["norm"]
x:
  pt: ["PT"]
units:
  GeV: ["GEV", "GEV/c"]
"""

CENTRALITY = """
TEST_V0M:
  experiment: ALICE
  quantity: charged_multiplicity
  detector: scintillators
  eta_range: [[2.8, 5.1], [-3.7, -1.7]]
  reference: "a paper"
TEST_HF:
  experiment: CMS
  quantity: energy
  detector: forward calorimeters
  eta_range: [[3.0, 5.0]]
  reference: "another paper"
"""

OBSERVABLES = """
fields:
  centrality: { type: range }
  centrality_definition: { type: centrality_definition }
  reference_centrality: { type: range }
  harmonic: { type: integer, minimum: 1 }
  method: { type: enum, values: [SP, EP, cumulant2] }
  definition: { type: enum, where: y, values: [CROSS_SECTION_DPT_DY, INVARIANT_YIELD_DETA] }
  variant: { type: token }
  eta_range: { type: range, where: acceptance, global: true }
  abs_eta_range: { type: range, where: acceptance, global: true }
  y_range: { type: range, where: acceptance, global: true }
  delta_eta_gap: { type: number, minimum: 0, where: acceptance }
observables:
  raa:
    x: [pt]
    systems: [PbPb, pPb]
    required: [centrality, centrality_definition]
    optional: [variant]
    distinguish: [variant]
    final: HADRON_RAA
  rcp:
    x: [pt]
    systems: [PbPb]
    required: [centrality, centrality_definition, reference_centrality]
    final: HADRON_RAA
  vn:
    x: [pt]
    systems: [PbPb]
    required: [centrality, centrality_definition, harmonic, method]
    optional: [delta_eta_gap]
    distinguish: [method, harmonic, delta_eta_gap]
    key_format: { harmonic: "n{}", delta_eta_gap: "gap{}" }
    final: { by: method, kinds: { SP: HADRON_VN_SP } }
  pp_cross_section:
    y: cross_section
    x: [pt]
    systems: [pp]
    required: [definition]
    distinguish: [definition]
    final: HADRON_CROSS_SECTION
"""


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    return path


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """An empty data repository with the small test registry."""
    write(tmp_path / "aliases.yaml", ALIASES)
    write(tmp_path / "centrality_definitions.yaml", CENTRALITY)
    write(tmp_path / "observables.yaml", OBSERVABLES)
    (tmp_path / "data").mkdir()
    (tmp_path / "recipes").mkdir()
    return tmp_path


def bins(n: int = 3, start: float = 5.0, step: float = 1.0) -> list[dict[str, float]]:
    return [{"low": start + i * step, "high": start + (i + 1) * step} for i in range(n)]


def cell(value: Any, *errors: dict[str, Any]) -> dict[str, Any]:
    return {"value": value, "errors": list(errors)}


def sym(label: str, value: Any) -> dict[str, Any]:
    return {"label": label, "symerror": value}


def asym(label: str, minus: Any, plus: Any) -> dict[str, Any]:
    return {"label": label, "asymerror": {"minus": minus, "plus": plus}}


def column(
    name: str = "RAA",
    values: list[dict[str, Any]] | None = None,
    qualifiers: dict[str, str] | None = None,
    units: str | None = None,
) -> dict[str, Any]:
    header: dict[str, Any] = {"name": name}
    if units:
        header["units"] = units
    return {
        "header": header,
        "qualifiers": [{"name": k, "value": v} for k, v in (qualifiers or {}).items()],
        "values": values
        if values is not None
        else [cell(0.5, sym("stat", 0.01), sym("sys", 0.02)) for _ in range(3)],
    }


def table(
    name: str = "Table 1",
    columns: list[dict[str, Any]] | None = None,
    x: list[dict[str, Any]] | None = None,
    x_name: str = "PT",
    x_units: str | None = "GEV",
    description: str = "A test table.",
    location: str = "Data from Fig. 1",
) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "location": location,
        "x": [{"header": {"name": x_name, **({"units": x_units} if x_units else {})},
               "values": x if x is not None else bins()}],  # fmt: skip
        "columns": columns if columns is not None else [column()],
    }


def write_record(
    root: Path,
    tables: list[dict[str, Any]],
    inspire_id: int = 1001,
    version: int = 1,
    place: str = "data/5020/hadron/test",
    comment: str = "",
) -> Path:
    directory = root / place / f"HEPData-ins{inspire_id}-v{version}-yaml"
    directory.mkdir(parents=True, exist_ok=True)
    documents: list[Any] = [
        {"hepdata_doi": f"10.17182/hepdata.{inspire_id}.v{version}", "comment": comment}
    ]
    for index, spec in enumerate(tables, start=1):
        data_file = f"data{index}.yaml"
        documents.append(
            {
                "name": spec["name"],
                "data_file": data_file,
                "description": spec["description"],
                "location": spec["location"],
                "table_doi": f"10.17182/hepdata.{inspire_id}.v{version}/t{index}",
            }
        )
        (directory / data_file).write_text(
            yaml.safe_dump(
                {
                    "independent_variables": spec["x"],
                    "dependent_variables": spec["columns"],
                }
            ),
            encoding="utf-8",
        )
    (directory / "submission.yaml").write_text(
        yaml.safe_dump_all(documents), encoding="utf-8"
    )
    return directory


def write_recipe(root: Path, text: str, name: str = "ins1001.yaml") -> Path:
    return write(root / "recipes" / name, text)


BASIC_RECIPE = """
record: { inspire_id: 1001, version: 1 }
paper: "arXiv:0000.00000"
experiment: CMS
particle: charged
sqrt_s_nn: 5020
centrality_definition: TEST_HF
acceptance: { eta_range: [-1.0, 1.0] }
datasets:
  - { table: Table 1, observable: raa, system: PbPb, centrality: [0, 5] }
"""
