"""T87: the MSSQL query texts are valid T-SQL and rows_to_skeleton turns rows into a canonical skeleton.

The rows here are hand-built in the column order MSSQL_QUERIES selects, so the conversion is tested
without a server; the pyodbc path is never exercised (PLAN R3-4).
"""

import pytest
import sqlglot

from nl2sql.schema_map import introspect

TABLE_ROWS = [
    ("dbo", "TBLSTGRUP"),
    ("dbo", "TBLSTSABIT"),
]

COLUMN_ROWS = [
    ("dbo", "TBLSTGRUP", "GRUP_KODU", "varchar", 12, None, None, "NO"),
    ("dbo", "TBLSTGRUP", "GRUP_ISIMI", "nvarchar", 60, None, None, "NO"),
    ("dbo", "TBLSTSABIT", "STOK_KODU", "varchar", 20, None, None, "NO"),
    ("dbo", "TBLSTSABIT", "FIYAT", "decimal", None, 18, 2, "NO"),
    ("dbo", "TBLSTSABIT", "ADET", "int", None, 10, 0, "YES"),
    ("dbo", "TBLSTSABIT", "TARIH", "date", None, None, None, "YES"),
    ("dbo", "TBLSTSABIT", "NOTLAR", "nvarchar", -1, None, None, "YES"),
    ("dbo", "TBLSTSABIT", "GRUP_KODU", "varchar", 12, None, None, "YES"),
    # INFORMATION_SCHEMA.COLUMNS lists view columns too; a view is not part of a skeleton.
    ("dbo", "VW_SATISLAR", "STOK_KODU", "varchar", 20, None, None, "YES"),
]

FK_ROWS = [
    ("dbo", "TBLSTSABIT", "GRUP_KODU", "dbo", "TBLSTGRUP", "GRUP_KODU"),
    # A foreign key onto a table the table query did not return has nowhere to be written.
    ("dbo", "VW_SATISLAR", "STOK_KODU", "dbo", "TBLSTSABIT", "STOK_KODU"),
]


@pytest.fixture(scope="module")
def skeleton():
    return introspect.rows_to_skeleton(TABLE_ROWS, COLUMN_ROWS, FK_ROWS)


def _table(skeleton, name):
    return next(table for table in skeleton["tables"] if table["name"] == name)


def _column(skeleton, table_name, column_name):
    table = _table(skeleton, table_name)
    return next(column for column in table["columns"] if column["name"] == column_name)


def test_every_query_parses_as_tsql():
    assert set(introspect.MSSQL_QUERIES) == {"tables", "columns", "foreign_keys"}
    for name, sql in introspect.MSSQL_QUERIES.items():
        assert sqlglot.parse_one(sql, read="tsql") is not None, name


def test_skeleton_lists_the_tables_in_the_order_they_came(skeleton):
    assert [table["name"] for table in skeleton["tables"]] == ["TBLSTGRUP", "TBLSTSABIT"]


def test_skeleton_lists_the_columns_in_the_order_they_came(skeleton):
    assert [c["name"] for c in _table(skeleton, "TBLSTSABIT")["columns"]] == [
        "STOK_KODU",
        "FIYAT",
        "ADET",
        "TARIH",
        "NOTLAR",
        "GRUP_KODU",
    ]


def test_types_carry_the_size_schema_json_writes(skeleton):
    types = {
        name: _column(skeleton, "TBLSTSABIT", name)["type"]
        for name in ("STOK_KODU", "FIYAT", "ADET", "TARIH", "NOTLAR")
    }
    assert types == {
        "STOK_KODU": "VARCHAR(20)",
        "FIYAT": "DECIMAL(18,2)",
        "ADET": "INT",
        "TARIH": "DATE",
        "NOTLAR": "NVARCHAR(MAX)",
    }


def test_nullability_comes_from_the_yes_no_column(skeleton):
    assert _column(skeleton, "TBLSTSABIT", "STOK_KODU")["nullable"] is False
    assert _column(skeleton, "TBLSTSABIT", "GRUP_KODU")["nullable"] is True


def test_foreign_key_is_referenced_table_dot_column(skeleton):
    assert _column(skeleton, "TBLSTSABIT", "GRUP_KODU")["fk"] == "TBLSTGRUP.GRUP_KODU"
    assert _column(skeleton, "TBLSTGRUP", "GRUP_KODU")["fk"] is None


def test_a_view_is_not_a_table_and_its_foreign_key_row_is_ignored(skeleton):
    assert "VW_SATISLAR" not in {table["name"] for table in skeleton["tables"]}
    assert _column(skeleton, "TBLSTSABIT", "STOK_KODU")["fk"] is None


def test_skeleton_carries_no_meaning(skeleton):
    for table in skeleton["tables"]:
        assert table["kind"] == "unknown"
        assert table["description"] == ""
        assert table["module"] == ""
        for column in table["columns"]:
            assert column["description"] == ""
            assert column["values"] == {}


def test_tables_and_columns_carry_exactly_the_canonical_fields():
    built = introspect.rows_to_skeleton([("dbo", "T")], [("dbo", "T", "A", "int", None, None, None, "NO")], [])
    assert built["tables"][0].keys() == {"name", "description", "module", "kind", "columns"}
    assert built["tables"][0]["columns"][0].keys() == {"name", "type", "description", "fk", "values", "nullable"}


def test_missing_connection_names_the_env_var(monkeypatch):
    monkeypatch.delenv("NL2SQL_MSSQL_CONN", raising=False)
    with pytest.raises(introspect.IntrospectError) as excinfo:
        introspect.mssql_skeleton()
    assert "NL2SQL_MSSQL_CONN" in str(excinfo.value)
