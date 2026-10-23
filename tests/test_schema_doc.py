import inspect
import json
import re

import pytest

from nl2sql import config
from nl2sql.schema_map import doc

BRIEF_TABLES = {
    "TBLSTGRUP",
    "TBLSTSABIT",
    "TBLDEPO",
    "TBLPLASIYER",
    "TBLCASABIT",
    "TBLFATUIRS",
    "TBLSTHAR",
    "TBLCAHAR",
    "TBLSIPAMAS",
    "TBLSIPATRA",
}

# PLAN Decision 4: the coded columns generator, schema doc and golden SQL must agree on.
DECISION4_CODES = {
    ("TBLCASABIT", "CARI_TIP"): {"A", "S", "H"},
    ("TBLFATUIRS", "FTIRSIP"): {"1", "2", "3"},
    ("TBLFATUIRS", "IPTAL"): {"E", "H"},
    ("TBLSTHAR", "STHAR_GCKOD"): {"G", "C"},
    ("TBLSTHAR", "STHAR_HTUR"): {"S", "A", "I", "T", "D"},
    ("TBLCAHAR", "BA"): {"B", "A"},
}

TYPE_RE = re.compile(r"^(INT|DATE|VARCHAR\(\d+\)|NVARCHAR\(\d+\)|DECIMAL\(\d+,\d+\)|REAL)$")
NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
FK_RE = re.compile(r"^[A-Z][A-Z0-9_]*\.[A-Z][A-Z0-9_]*$")


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def columns_by_table(schema):
    return {table["name"]: {c["name"] for c in table["columns"]} for table in schema["tables"]}


def table_map(schema):
    return {table["name"]: table for table in schema["tables"]}


def column(schema, table_name, column_name):
    for table in schema["tables"]:
        if table["name"] == table_name:
            for column_ in table["columns"]:
                if column_["name"] == column_name:
                    return column_
    raise AssertionError(f"{table_name}.{column_name} yok")


# ----------------------------------------------------------------- shape


def test_ten_brief_tables(schema):
    names = [table["name"] for table in schema["tables"]]
    assert BRIEF_TABLES <= set(names)
    assert len(set(names)) == len(names)


def test_table_names_uppercase_and_documented(schema):
    for table in schema["tables"]:
        assert NAME_RE.match(table["name"]), table["name"]
        assert table["description"].strip(), table["name"]
        assert table["module"].strip(), table["name"]


def test_columns_have_type_description_and_nullability(schema):
    for table in schema["tables"]:
        names = [c["name"] for c in table["columns"]]
        assert len(names) >= 3, table["name"]
        assert len(set(names)) == len(names), table["name"]
        for column_ in table["columns"]:
            assert NAME_RE.match(column_["name"]), column_["name"]
            assert TYPE_RE.match(column_["type"]), (table["name"], column_["type"])
            assert column_["description"].strip(), (table["name"], column_["name"])
            assert isinstance(column_["nullable"], bool), column_["name"]


def test_money_is_decimal_and_dates_are_date(schema):
    money = {
        ("TBLFATUIRS", "GENELTOPLAM"),
        ("TBLSTHAR", "STHAR_NF"),
        ("TBLSTHAR", "STHAR_GCMIK"),
        ("TBLCAHAR", "TUTAR"),
        ("TBLSIPAMAS", "TOPLAM_TUTAR"),
        ("TBLSIPATRA", "TUTAR"),
    }
    for table_name, column_name in money:
        assert column(schema, table_name, column_name)["type"] == "DECIMAL(18,2)", column_name
    for table_name, column_name in {
        ("TBLFATUIRS", "TARIH"),
        ("TBLSTHAR", "STHAR_TARIH"),
        ("TBLCAHAR", "TARIH"),
        ("TBLSIPAMAS", "TARIH"),
        ("TBLSIPATRA", "TESLIM_TARIHI"),
    }:
        assert column(schema, table_name, column_name)["type"] == "DATE", column_name


def test_primary_key_columns_are_not_nullable(schema):
    for table in schema["tables"]:
        keys = [c for c in table["columns"] if "birincil anahtar" in c["description"]]
        assert len(keys) == 1, table["name"]
        assert not keys[0]["nullable"], keys[0]["name"]


# ----------------------------------------------------------------- foreign keys


def test_fk_syntax_and_targets_exist(schema):
    index = {(table["name"], c["name"]) for table in schema["tables"] for c in table["columns"]}
    for table in schema["tables"]:
        for column_ in table["columns"]:
            fk = column_["fk"]
            assert fk is None or isinstance(fk, str), column_["name"]
            if fk is None:
                continue
            assert FK_RE.match(fk), (table["name"], column_["name"], fk)
            target = tuple(fk.split("."))
            assert target in index, f"{table['name']}.{column_['name']} -> {fk} yok"
            assert target != (table["name"], column_["name"]), fk


def test_expected_relationships(schema):
    expected = {
        ("TBLSTSABIT", "GRUP_KODU"): "TBLSTGRUP.GRUP_KODU",
        ("TBLCASABIT", "PLASIYER_KODU"): "TBLPLASIYER.PLASIYER_KODU",
        ("TBLFATUIRS", "CARI_KODU"): "TBLCASABIT.CARI_KOD",
        ("TBLSTHAR", "STOK_KODU"): "TBLSTSABIT.STOK_KODU",
        ("TBLSTHAR", "DEPO_KODU"): "TBLDEPO.DEPO_KODU",
        ("TBLSTHAR", "FISNO"): "TBLFATUIRS.FATIRS_NO",
        ("TBLSTHAR", "CARI_KODU"): "TBLCASABIT.CARI_KOD",
        ("TBLCAHAR", "CARI_KODU"): "TBLCASABIT.CARI_KOD",
        ("TBLCAHAR", "FISNO"): "TBLFATUIRS.FATIRS_NO",
        ("TBLSIPAMAS", "CARI_KODU"): "TBLCASABIT.CARI_KOD",
        ("TBLSIPATRA", "SIPARIS_NO"): "TBLSIPAMAS.SIPARIS_NO",
        ("TBLSIPATRA", "STOK_KODU"): "TBLSTSABIT.STOK_KODU",
    }
    for (table_name, column_name), target in expected.items():
        assert column(schema, table_name, column_name)["fk"] == target


# ----------------------------------------------------------------- coded values


def test_decision4_coded_columns(schema):
    for (table_name, column_name), codes in DECISION4_CODES.items():
        column_ = column(schema, table_name, column_name)
        assert set(column_["values"]) == codes, column_name
        assert all(str(meaning).strip() for meaning in column_["values"].values()), column_name


def test_coded_meanings_match_plan(schema):
    values = column(schema, "TBLCASABIT", "CARI_TIP")["values"]
    assert "alıcı" in values["A"] and "satıcı" in values["S"]
    assert values["H"].startswith("hem")
    values = column(schema, "TBLFATUIRS", "FTIRSIP")["values"]
    assert values["1"] == "satış faturası"
    assert values["2"] == "alış faturası"
    assert "iade" in values["3"]
    assert column(schema, "TBLFATUIRS", "IPTAL")["values"] == {"E": "iptal edilmiş", "H": "geçerli"}
    values = column(schema, "TBLSTHAR", "STHAR_GCKOD")["values"]
    assert values == {"G": "giriş", "C": "çıkış"}
    values = column(schema, "TBLSTHAR", "STHAR_HTUR")["values"]
    assert "çıkış" in values["S"] and "giriş" in values["A"]
    assert "iade" in values["I"] and "transfer" in values["T"] and "sayım" in values["D"]
    assert column(schema, "TBLCAHAR", "BA")["values"] == {"B": "borç", "A": "alacak"}


def test_every_coded_column_documents_every_value(schema):
    for table in schema["tables"]:
        for column_ in table["columns"]:
            if not column_["values"]:
                continue
            assert len(column_["values"]) >= 2, column_["name"]
            for code, meaning in column_["values"].items():
                assert code.strip() and meaning.strip(), column_["name"]
                assert not meaning.startswith(code), column_["name"]


# ----------------------------------------------------------------- trap columns


def test_trap_columns_exist_and_are_documented(schema, columns_by_table):
    assert columns_by_table["TBLSTHAR"] >= {"FISNO", "STHAR_HTUR", "STHAR_NF", "DEPO_KODU"}
    assert column(schema, "TBLSTHAR", "FISNO")["nullable"] is True
    assert column(schema, "TBLSIPATRA", "TESLIM_TARIHI")["nullable"] is True
    assert column(schema, "TBLCASABIT", "PLASIYER_KODU")["nullable"] is True
    assert "NULL" in column(schema, "TBLSIPATRA", "TESLIM_TARIHI")["description"]
    assert "geçersiz" in column(schema, "TBLFATUIRS", "IPTAL")["description"]
    assert "Kart" in column(schema, "TBLSTSABIT", "BIRIM_FIYAT")["description"]


# ----------------------------------------------------------------- allowlist


def test_allowlist_is_uppercase_table_names(schema):
    # ASSUMPTION: the allowlist is every schema table (Decision 6), so R2-3's new tables are allowed too.
    assert doc.allowlist(schema) >= {name.upper() for name in BRIEF_TABLES}
    assert all(name.isupper() for name in doc.allowlist(schema))


# ----------------------------------------------------------------- compact text


def test_compact_text_one_line_per_table(schema):
    text = doc.compact_text(schema)
    lines = text.splitlines()
    assert len(lines) == len(schema["tables"])
    for table, line in zip(schema["tables"], lines):
        assert line.startswith(table["name"] + " ")
        assert table["description"] in line
        assert f"[{table['module']}]" in line


def test_compact_text_has_no_column_names(schema):
    text = doc.compact_text(schema)
    assert "STHAR_GCMIK" not in text
    assert "->" not in text


# ----------------------------------------------------------------- table detail


def test_table_detail_lists_columns_types_fk_and_codes(schema):
    text = doc.table_detail(schema, ["TBLSTHAR"])
    assert text.startswith("TBLSTHAR — ")
    for column_ in table_map(schema)["TBLSTHAR"]["columns"]:
        assert column_["name"] in text
        assert column_["type"] in text
    assert "-> TBLFATUIRS.FATIRS_NO" in text
    assert "G=giriş" in text and "C=çıkış" in text
    assert "I=satış iadesi" in text
    assert "STHAR_ID INT NOT NULL" in text
    assert "FISNO VARCHAR(20) —" in text


def test_table_detail_multiple_tables_in_request_order(schema):
    text = doc.table_detail(schema, ["TBLDEPO", "TBLCASABIT"])
    assert text.index("TBLDEPO —") < text.index("TBLCASABIT —")
    assert "CARI_TIP" in text and "hem alıcı hem satıcı" in text


def test_table_detail_is_case_insensitive_and_trims(schema):
    assert doc.table_detail(schema, [" tblsthar "]) == doc.table_detail(schema, ["TBLSTHAR"])


def test_table_detail_never_prints_none(schema):
    text = doc.table_detail(schema, sorted(BRIEF_TABLES))
    assert "None" not in text
    assert "-> ," not in text


def test_table_detail_unknown_table_is_short_error(schema):
    text = doc.table_detail(schema, ["TBLFOO"])
    assert "TBLFOO" in text
    assert len(text.splitlines()) == 1
    assert len(text) < 400
    assert "STOK_KODU" not in text
    for name in BRIEF_TABLES:
        assert name in text


def test_table_detail_unknown_name_among_known_ones_still_errors(schema):
    text = doc.table_detail(schema, ["TBLSTGRUP", "SYSOBJECTS"])
    assert "SYSOBJECTS" in text
    assert "GRUP_KODU" not in text


def test_table_detail_empty_request_lists_known_tables(schema):
    text = doc.table_detail(schema, [])
    assert len(text.splitlines()) == 1
    for name in BRIEF_TABLES:
        assert name in text


# ----------------------------------------------------------------- loader


def test_load_schema_path_defaults_to_config():
    assert inspect.signature(doc.load_schema).parameters["path"].default == config.SCHEMA_PATH


def test_load_schema_fills_optional_fields(tmp_path):
    path = tmp_path / "schema.json"
    path.write_text(
        json.dumps({"tables": [{"name": "TBLX", "columns": [{"name": "A", "type": "INT"}]}]}),
        encoding="utf-8",
    )
    table = doc.load_schema(path)["tables"][0]
    assert table["description"] == "" and table["module"] == ""
    column_ = table["columns"][0]
    assert (column_["fk"], column_["values"], column_["nullable"], column_["description"]) == (
        None,
        {},
        True,
        "",
    )


def test_load_schema_keeps_explicit_values(tmp_path):
    path = tmp_path / "schema.json"
    path.write_text(
        json.dumps(
            {
                "tables": [
                    {
                        "name": "TBLX",
                        "description": "x",
                        "module": "m",
                        "columns": [
                            {"name": "A", "type": "INT", "description": "d", "fk": "TBLY.B", "values": {"E": "e"}, "nullable": False}
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    column_ = doc.load_schema(path)["tables"][0]["columns"][0]
    assert column_["fk"] == "TBLY.B" and column_["nullable"] is False and column_["values"] == {"E": "e"}


def test_real_schema_is_utf8_json_with_turkish_text():
    raw = config.SCHEMA_PATH.read_text(encoding="utf-8")
    assert "çıkış" in raw and "iptal" in raw
    assert json.loads(raw)["tables"][0]["name"] == "TBLSTGRUP"
