import math

import pytest

from conftest import column, table, write_record
from hsdc import raw
from hsdc.raw import Parsed, RawError, parse_number


@pytest.mark.parametrize(
    "cell, expected",
    [
        (0.5, Parsed(0.5)),
        (3, Parsed(3)),
        ("1.4166e-03", Parsed(0.0014166)),
        ("5360", Parsed(5360)),
        ("-2.5", Parsed(-2.5)),
        ("5.2%", Parsed(5.2, True)),
        ("-3 %", Parsed(-3, True)),
        ("", Parsed(None)),
        ("--", Parsed(None)),
        ("  n/a ", Parsed(None)),
        (None, Parsed(None)),
        (math.nan, Parsed(None)),
        ("NaN", Parsed(None)),
    ],
)
def test_parse_number(cell, expected):
    assert parse_number(cell) == expected


@pytest.mark.parametrize("cell", ["abc", "1.2.3", True, [1], {"a": 1}])
def test_parse_number_refuses_what_it_cannot_read(cell):
    with pytest.raises(RawError):
        parse_number(cell)


def test_numeric_strings_keep_their_integer_or_float_type():
    assert isinstance(parse_number("5").value, int)
    assert isinstance(parse_number("5.0").value, float)


def test_record_is_found_and_read(root):
    write_record(root, [table("Table 1"), table("Table 2", columns=[column(), column()])],
                 inspire_id=77, version=2, comment="hello")  # fmt: skip
    record = raw.open_record(root, 77, 2)
    assert (record.inspire_id, record.version, record.comment) == (77, 2, "hello")
    assert list(record.tables) == ["Table 1", "Table 2"]
    data = record.table("Table 2").data
    assert len(data.dependent) == 2
    assert data.independent[0].name == "PT" and data.independent[0].units == "GEV"
    assert record.table("Table 1").doi.endswith("/t1")


def test_missing_record_and_table_say_what_is_missing(root):
    with pytest.raises(RawError, match="ins5 v1 is not under data/"):
        raw.open_record(root, 5, 1)
    write_record(root, [table("Table 1")], inspire_id=5)
    with pytest.raises(RawError, match="no table 'Table 9'"):
        raw.open_record(root, 5, 1).table("Table 9")


def test_identical_copies_of_a_record_are_one_record(root):
    write_record(root, [table()], inspire_id=9, place="data/2760/hadron/a")
    write_record(root, [table()], inspire_id=9, place="data/5020/hadron/b")
    assert raw.open_record(root, 9, 1).inspire_id == 9


def test_differing_copies_are_refused(root):
    write_record(root, [table()], inspire_id=9, place="data/2760/hadron/a")
    write_record(root, [table(description="changed")], inspire_id=9, place="data/5020/hadron/b")
    with pytest.raises(RawError, match="differ"):
        raw.open_record(root, 9, 1)


def test_versions_are_kept_apart(root):
    write_record(root, [table(description="first")], inspire_id=9, version=1)
    write_record(root, [table(description="second")], inspire_id=9, version=2)
    assert raw.open_record(root, 9, 1).table("Table 1").description == "first"
    assert raw.open_record(root, 9, 2).table("Table 1").description == "second"


def test_variable_qualifier_lookup_ignores_case(root):
    write_record(root, [table(columns=[column(qualifiers={"CENT": "0-5 pct"})])])
    variable = raw.open_record(root, 1001, 1).table("Table 1").data.dependent[0]
    assert variable.qualifier("centrality", "cent").value == "0-5 pct"
    assert variable.qualifier("eta") is None
