# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T127: qualified names survive both introspection paths (PLAN R4-6).

A SQLite file stores a table's whole name as one identifier, so a qualified build reads back
"Sales.Orders" and a foreign key onto it names that same dotted identifier; a dbo spelling is stored
exactly as it was written. SQL Server keeps the schema in its own column instead, so
rows_to_skeleton joins it back: a schema of its own goes into the name, dbo does not, and a foreign
key target follows the same rule.
"""

import sqlite3

import pytest

from bilgin.schema_map import build, introspect

SCHEMA = {
    "tables": [
        {
            "name": "Sales.Orders",
            "columns": [
                {"name": "OrderID", "type": "INT", "nullable": False},
                {"name": "CustomerID", "type": "INT", "nullable": False},
                {"name": "OrderDate", "type": "DATETIME2", "nullable": True},
                {"name": "Active", "type": "BIT", "nullable": False},
                {"name": "RowVersion", "type": "VARBINARY", "nullable": True},
                {"name": "Note", "type": "VARCHAR(200)", "nullable": True},
                {"name": "Total", "type": "DECIMAL(18,2)", "nullable": False},
            ],
        },
        {
            "name": "dbo.TBLCASABIT",
            "columns": [
                {"name": "CARI_KOD", "type": "VARCHAR(10)", "nullable": False},
                {"name": "IPTAL", "type": "BIT", "nullable": False},
            ],
        },
        {
            "name": "TBLSTGRUP",
            "columns": [{"name": "GRUP_KODU", "type": "VARCHAR(12)", "nullable": False}],
        },
    ]
}

TABLE_ROWS = [
    ("dbo", "TBLSTGRUP"),
    ("Sales", "Customers"),
    ("Sales", "Orders"),
    ("Application", "People"),
]

COLUMN_ROWS = [
    ("dbo", "TBLSTGRUP", "GRUP_KODU", "varchar", 12, None, None, "NO"),
    ("Sales", "Customers", "CustomerID", "int", None, 10, 0, "NO"),
    ("Sales", "Customers", "Name", "nvarchar", 50, None, None, "NO"),
    ("Sales", "Customers", "PersonID", "int", None, 10, 0, "YES"),
    ("Sales", "Orders", "OrderID", "int", None, 10, 0, "NO"),
    ("Sales", "Orders", "CustomerID", "int", None, 10, 0, "NO"),
    ("Sales", "Orders", "GroupCode", "varchar", 12, None, None, "YES"),
    ("Application", "People", "PersonID", "int", None, 10, 0, "NO"),
]

FK_ROWS = [
    ("Sales", "Customers", "PersonID", "Application", "People", "PersonID"),
    ("Sales", "Orders", "CustomerID", "Sales", "Customers", "CustomerID"),
    # A foreign key onto a dbo table names it bare, the way the table itself is named.
    ("Sales", "Orders", "GroupCode", "dbo", "TBLSTGRUP", "GRUP_KODU"),
]


@pytest.fixture(scope="module")
def skeleton(tmp_path_factory):
    """A hand-built qualified schema written to a real SQLite file and read back from it."""
    path = tmp_path_factory.mktemp("introspect-qualified") / "test.db"
    build.write_sqlite({}, SCHEMA, path)
    return introspect.sqlite_skeleton(path)


@pytest.fixture(scope="module")
def mssql():
    """Hand-built rows in the order MSSQL_QUERIES selects, over two schemas next to dbo."""
    return introspect.rows_to_skeleton(TABLE_ROWS, COLUMN_ROWS, FK_ROWS)


def _affinity(type_name: str) -> str:
    """The SQLite type build.py gives a T-SQL type - all a SQLite file can carry back."""
    return build.SQLITE_TYPES[str(type_name).split("(")[0].upper()]


def _table(skeleton, name):
    return next(table for table in skeleton["tables"] if table["name"] == name)


def _column(skeleton, table_name, column_name):
    return next(
        column for column in _table(skeleton, table_name)["columns"] if column["name"] == column_name
    )


# ------------------------------------------------------------------ sqlite: the stored name is the name


def test_sqlite_skeleton_keeps_the_stored_dotted_names(skeleton):
    assert [table["name"] for table in skeleton["tables"]] == [
        "Sales.Orders",
        "dbo.TBLCASABIT",
        "TBLSTGRUP",
    ]


def test_sqlite_skeleton_matches_the_built_schema_on_names_and_nullability(skeleton):
    for table, built in zip(SCHEMA["tables"], skeleton["tables"]):
        assert [c["name"] for c in built["columns"]] == [c["name"] for c in table["columns"]]
        for column, skel in zip(table["columns"], built["columns"]):
            where = f"{built['name']}.{column['name']}"
            assert skel["nullable"] is column["nullable"], where
            # build.py declares no FOREIGN KEY constraints, so the built file has no fk to read back.
            assert skel["fk"] is None, where


def test_sqlite_skeleton_types_invert_the_build_type_mapping(skeleton):
    for table, built in zip(SCHEMA["tables"], skeleton["tables"]):
        for column, skel in zip(table["columns"], built["columns"]):
            assert _affinity(skel["type"]) == _affinity(column["type"]), f"{built['name']}.{column['name']}"


def test_the_run4_types_come_back_as_their_own_tsql_names(skeleton):
    types = {column["name"]: column["type"] for column in _table(skeleton, "Sales.Orders")["columns"]}
    assert types == {
        "OrderID": "INT",
        "CustomerID": "INT",
        "OrderDate": "DATETIME",
        "Active": "BIT",
        "RowVersion": "VARBINARY",
        "Note": "VARCHAR",
        "Total": "DECIMAL",
    }


def test_a_foreign_key_onto_a_qualified_table_names_the_stored_identifier(tmp_path):
    path = tmp_path / "fk.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        'CREATE TABLE "Sales.Customers" ("CustomerID" INTEGER NOT NULL, PRIMARY KEY ("CustomerID"));\n'
        'CREATE TABLE "Sales.Orders" ("OrderID" INTEGER NOT NULL, "CustomerID" INTEGER NOT NULL, '
        'FOREIGN KEY ("CustomerID") REFERENCES "Sales.Customers" ("CustomerID"));'
    )
    conn.commit()
    conn.close()

    tables = {table["name"]: table for table in introspect.sqlite_skeleton(path)["tables"]}
    assert tables["Sales.Orders"]["columns"][1]["fk"] == "Sales.Customers.CustomerID"
    assert tables["Sales.Customers"]["columns"][0]["fk"] is None


# ------------------------------------------------------------------ sql server: the schema column joins back


def test_mssql_skeleton_qualifies_every_table_of_its_own_schema(mssql):
    assert [table["name"] for table in mssql["tables"]] == [
        "TBLSTGRUP",
        "Sales.Customers",
        "Sales.Orders",
        "Application.People",
    ]


def test_columns_land_in_the_table_of_their_own_schema(mssql):
    assert [c["name"] for c in _table(mssql, "Sales.Orders")["columns"]] == [
        "OrderID",
        "CustomerID",
        "GroupCode",
    ]


def test_a_foreign_key_target_follows_the_same_qualifying_rule(mssql):
    assert _column(mssql, "Sales.Customers", "PersonID")["fk"] == "Application.People.PersonID"
    assert _column(mssql, "Sales.Orders", "CustomerID")["fk"] == "Sales.Customers.CustomerID"
    assert _column(mssql, "Sales.Orders", "GroupCode")["fk"] == "TBLSTGRUP.GRUP_KODU"
    assert _column(mssql, "TBLSTGRUP", "GRUP_KODU")["fk"] is None
