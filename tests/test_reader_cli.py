import io
import json
import tarfile
from pathlib import Path

import pandas as pd
import pytest

from conftest import BASIC_RECIPE, asym, bins, cell, column, sym, table, write_record, write_recipe
from hsdc import cli, reader, updates, yamlio
from hsdc import registry as reg
from hsdc.reader import FormatError


def main(root, *args):
    return cli.main(["--root", str(root), *args])


@pytest.fixture
def built(root):
    values = [cell(0.5, sym("stat", 0.01), asym("sys,TAA", -0.02, 0.03)) for _ in range(3)]
    write_record(root, [table(columns=[column(values=values)])])
    write_recipe(root, BASIC_RECIPE)
    assert main(root, "build") == 0
    return root


# --- build and validate ------------------------------------------------------------------


def test_build_writes_the_file_and_the_schema_and_a_rebuild_changes_nothing(built, capsys):
    path = built / "curated/raa/PbPb5020/raa__PbPb5020__CMS__charged__0-5.yaml"
    assert path.exists() and (built / "schema/dataset.schema.json").exists()
    before = path.read_bytes()
    assert main(built, "build") == 0
    assert "0 written" in capsys.readouterr().out
    assert path.read_bytes() == before


def test_check_passes_when_current_and_fails_on_any_difference(built, capsys):
    assert main(built, "build", "--check") == 0
    path = built / "curated/raa/PbPb5020/raa__PbPb5020__CMS__charged__0-5.yaml"
    path.write_text(path.read_text().replace("0.5,", "0.6,", 1))
    assert main(built, "build", "--check") == 1
    assert "differs: curated/raa/PbPb5020" in capsys.readouterr().err
    path.unlink()
    assert main(built, "build", "--check") == 1
    assert "missing:" in capsys.readouterr().err


def test_check_reports_stale_files_and_build_removes_them(built, capsys):
    stale = built / "curated/raa/PbPb5020/old.yaml"
    stale.write_text("x: 1\n")
    assert main(built, "build", "--check") == 1
    assert "stale: curated/raa/PbPb5020/old.yaml" in capsys.readouterr().err
    assert main(built, "build") == 0
    assert not stale.exists()


def test_building_one_recipe_never_removes_anything(built):
    other = built / "curated/raa/PbPb5020/other.yaml"
    other.write_text("x: 1\n")
    assert main(built, "build", "--recipe", str(built / "recipes/ins1001.yaml")) == 0
    assert other.exists()


def test_validate_accepts_built_files_and_refuses_hand_damage(built, capsys):
    assert main(built, "validate") == 0
    path = built / "curated/raa/PbPb5020/raa__PbPb5020__CMS__charged__0-5.yaml"
    path.write_text(path.read_text().replace("particle: charged", "particle: pion"))
    assert main(built, "validate") == 1
    assert "key is" in capsys.readouterr().err


def test_validate_checks_where_a_generated_file_lives(built, capsys):
    path = built / "curated/raa/PbPb5020/raa__PbPb5020__CMS__charged__0-5.yaml"
    moved = built / "curated/raa/PbPb5020/renamed.yaml"
    path.rename(moved)
    assert main(built, "validate") == 1
    assert "belongs at curated/raa/PbPb5020/raa__PbPb5020__CMS__charged__0-5.yaml" in capsys.readouterr().err


def test_validate_checks_manual_files_too_and_keys_are_unique(built, capsys):
    source = built / "curated/raa/PbPb5020/raa__PbPb5020__CMS__charged__0-5.yaml"
    manual = built / "manual/typed.yaml"
    manual.parent.mkdir()
    manual.write_text(source.read_text())
    assert main(built, "validate") == 1
    assert "is also in" in capsys.readouterr().err


def test_errors_are_reported_without_a_traceback(root, capsys):
    write_recipe(root, BASIC_RECIPE)
    assert main(root, "build") == 2
    assert "error:" in capsys.readouterr().err


def test_tables_lists_what_a_recipe_needs(built, capsys):
    assert main(built, "tables", "1001", "1") == 0
    out = capsys.readouterr().out
    assert "Table 1" in out and "c0: 'RAA'" in out and "errors: ['stat', 'sys,TAA']" in out
    assert "x: 'PT' [GEV]  3 points" in out


# --- reader ------------------------------------------------------------------------------


def test_read_datasets_and_filters(built):
    found = reader.read_datasets(built)
    assert [d.key for d in found] == ["raa__PbPb5020__CMS__charged__0-5"]
    d = found[0]
    assert (d.system, d.sqrt_s_nn, d.centrality) == ("PbPb", 5020, (0, 5))
    assert d.has_edges and d.edges[0] == (5.0, 6.0) and d.centres == [None, None, None]
    assert d.bins[0].errors["taa"] == [-0.02, 0.03]
    assert d.get("eta_range") == [-1.0, 1.0] and d.get("system") == "PbPb" and d.get("none", 7) == 7

    assert reader.read_datasets(built, system="PbPb", centrality=[0, 5])
    assert reader.read_datasets(built, system=["pPb", "PbPb"], sqrt_s_nn=[5020, 2760])
    assert not reader.read_datasets(built, centrality=[0, 10])
    assert not reader.read_datasets(built, centrality=[[0, 10], [5, 10]])
    assert reader.read_datasets(built, centrality=[[0, 10], [0, 5]])
    assert not reader.read_datasets(built, system="pp")
    assert not reader.read_datasets(built, curated=False)


def test_tidy_has_one_row_per_bin(built):
    frame = reader.tidy(reader.read_datasets(built))
    assert len(frame) == 3
    assert list(frame.bin) == [0, 1, 2]
    assert frame.loc[0, ["low", "high", "value"]].tolist() == [5.0, 6.0, 0.5]
    assert frame.centrality_lo.tolist() == [0, 0, 0] and frame.centrality_hi.iloc[0] == 5


def test_tidy_errors_keeps_symmetric_and_asymmetric_apart(built):
    frame = reader.tidy_errors(reader.read_datasets(built))
    assert len(frame) == 6
    stat = frame[frame.source == "stat"].iloc[0]
    taa = frame[frame.source == "taa"].iloc[0]
    assert stat.symmetric == 0.01 and pd.isna(stat.minus) and pd.isna(stat.plus)
    assert pd.isna(taa.symmetric) and (taa.minus, taa.plus) == (-0.02, 0.03)
    assert taa.label == "sys,TAA" and taa.origin == "table" and not taa.percent


def test_a_file_of_another_format_version_is_refused(built):
    path = built / "curated/raa/PbPb5020/raa__PbPb5020__CMS__charged__0-5.yaml"
    path.write_text(path.read_text().replace("format_version: 1", "format_version: 2"))
    with pytest.raises(FormatError, match="format_version 2"):
        reader.read_datasets(built)


def test_find_root_honours_the_environment(built, monkeypatch, tmp_path):
    monkeypatch.setenv("HSDC_ROOT", str(built))
    assert reader.find_root(tmp_path) == built
    monkeypatch.delenv("HSDC_ROOT")
    assert reader.find_root(built / "recipes") == built


# --- the network parts, with a fake network ----------------------------------------------


def archive(inspire_id, version, description="new"):
    name = f"HEPData-ins{inspire_id}-v{version}-yaml"
    files = {
        "submission.yaml": f"hepdata_doi: 10.1/{inspire_id}.v{version}\n---\nname: Table 1\ndata_file: data1.yaml\ndescription: {description}\n",
        "data1.yaml": "independent_variables: []\ndependent_variables: []\n",
    }
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for filename, text in files.items():
            payload = text.encode()
            info = tarfile.TarInfo(f"{name}/{filename}")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def test_latest_version_reads_the_answer_and_refuses_a_surprise():
    assert updates.latest_version(5, fetch=lambda url: b'{"version": 3}') == 3
    assert updates.latest_version(5, fetch=lambda url: b'{"record": {"latest_version": 4}}') == 4
    with pytest.raises(updates.UpdateError, match="gave no version"):
        updates.latest_version(5, fetch=lambda url: b'{"other": 1}')
    with pytest.raises(updates.UpdateError, match="did not answer JSON"):
        updates.latest_version(5, fetch=lambda url: b"<html>")


def test_download_unpacks_the_record_and_refuses_an_existing_one(tmp_path):
    path = updates.download_record(7, 2, tmp_path, fetch=lambda url: archive(7, 2))
    assert path.name == "HEPData-ins7-v2-yaml" and (path / "submission.yaml").exists()
    with pytest.raises(updates.UpdateError, match="already exists"):
        updates.download_record(7, 2, tmp_path, fetch=lambda url: archive(7, 2))


def test_download_refuses_members_that_leave_the_folder(tmp_path):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 1
        tar.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(updates.UpdateError, match="would leave"):
        updates.download_record(7, 2, tmp_path / "data", fetch=lambda url: buffer.getvalue())
    assert not (tmp_path / "escape.txt").exists()


def test_repin_changes_only_the_version(tmp_path):
    recipe = write_recipe(tmp_path, "# comment\nrecord: { inspire_id: 12, version: 1 }\nx: 1\n")
    updates.repin(recipe, 5)
    assert recipe.read_text() == "# comment\nrecord: { inspire_id: 12, version: 5 }\nx: 1\n"
    recipe.write_text("record:\n  inspire_id: 12\n")
    with pytest.raises(updates.UpdateError, match="one-line"):
        updates.repin(recipe, 6)


def test_update_downloads_the_newer_version_and_moves_the_pin(built, monkeypatch, capsys):
    monkeypatch.setattr(updates, "fetch_url", lambda url: b'{"version": 2}' if "format=json" in url else archive(1001, 2))
    assert main(built, "check-updates") == 1
    assert "pinned v1  newest v2  NEWER" in capsys.readouterr().out
    assert main(built, "build", "--update", "--dry-run") == 0
    assert "version: 1" in (built / "recipes/ins1001.yaml").read_text()
    # The fake v2 has no tables, so the build after the update stops there -- but the pin moved
    # and the archive sits next to the old one.
    assert main(built, "build", "--update") == 2
    assert "version: 2" in (built / "recipes/ins1001.yaml").read_text()
    assert (built / "data/5020/hadron/test/HEPData-ins1001-v2-yaml/submission.yaml").exists()
    assert (built / "data/5020/hadron/test/HEPData-ins1001-v1-yaml").exists()


def test_fill_inspire_writes_a_file_the_build_reads(built, monkeypatch):
    answer = {"metadata": {"texkeys": ["CMS:2016abc"], "arxiv_eprints": [{"value": "1611.01664"}],
                           "titles": [{"title": "A title"}]}}  # fmt: skip
    monkeypatch.setattr(updates, "fetch_url", lambda url: json.dumps(answer).encode())
    assert main(built, "fill-inspire") == 0
    assert yamlio.load(built / "inspire.yaml")[1001]["texkey"] == "CMS:2016abc"
    assert main(built, "build") == 0
    dataset = reader.read_datasets(built)[0]
    assert dataset.source["inspireHEPKey"] == "CMS:2016abc"


def test_a_closed_pipe_is_not_an_error(built, monkeypatch, capsys):
    def broken(args):
        raise BrokenPipeError

    monkeypatch.setattr(cli, "cmd_tables", broken)
    assert main(built, "tables", "1001", "1") == 0
