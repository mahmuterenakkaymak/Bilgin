"""R2-3: the six new data tables - generator, schema doc, rules and golden SQL agree on these."""

import pytest

from nl2sql.schema_map import doc

DATA_TABLES = (
    "TBLSTOKFIAT",
    "TBLSTHAR_ARSIV",
    "TBLDOVKUR",
    "TBLCARISUBE",
    "TBLKAMPANYA",
    "TBLMUHFIS",
)

# PLAN R2-3's column list per table, in order. TBLSTHAR_ARSIV is checked against TBLSTHAR instead.
COLUMNS = {
    "TBLSTOKFIAT": ["FIAT_ID", "STOK_KODU", "FIYAT_TIPI", "FIYAT", "GECERLILIK_TARIHI"],
    "TBLDOVKUR": ["KUR_TARIH", "DOVIZ_KODU", "ALIS", "SATIS"],
    "TBLCARISUBE": ["SUBE_KODU", "CARI_KOD", "SUBE_ADI", "IL", "ILCE", "AKTIF"],
    "TBLKAMPANYA": ["KAMPANYA_KODU", "KAMPANYA_ADI", "STOK_KODU", "BASLANGIC", "BITIS", "INDIRIM_ORANI"],
    "TBLMUHFIS": ["MUHFIS_ID", "FIS_NO", "TARIH", "HESAP_KODU", "BA", "TUTAR", "FATIRS_NO"],
}

FK = {
    ("TBLSTOKFIAT", "STOK_KODU"): "TBLSTSABIT.STOK_KODU",
    ("TBLSTHAR_ARSIV", "STOK_KODU"): "TBLSTSABIT.STOK_KODU",
    ("TBLSTHAR_ARSIV", "DEPO_KODU"): "TBLDEPO.DEPO_KODU",
    ("TBLSTHAR_ARSIV", "CARI_KODU"): "TBLCASABIT.CARI_KOD",
    ("TBLCARISUBE", "CARI_KOD"): "TBLCASABIT.CARI_KOD",
    ("TBLKAMPANYA", "STOK_KODU"): "TBLSTSABIT.STOK_KODU",
    ("TBLMUHFIS", "FATIRS_NO"): "TBLFATUIRS.FATIRS_NO",
}

CODE_SETS = {
    ("TBLSTOKFIAT", "FIYAT_TIPI"): {"S", "A"},
    ("TBLDOVKUR", "DOVIZ_KODU"): {"USD", "EUR"},
    ("TBLCARISUBE", "AKTIF"): {"E", "H"},
    ("TBLSTHAR_ARSIV", "STHAR_GCKOD"): {"G", "C"},
    ("TBLSTHAR_ARSIV", "STHAR_HTUR"): {"S", "A", "I", "T", "D"},
    ("TBLMUHFIS", "HESAP_KODU"): {"600", "610", "153", "391"},
    ("TBLMUHFIS", "BA"): {"B", "A"},
}

# The words PLAN R2-3 uses for the codes; the generator and the golden SQL are written from them.
MEANINGS = {
    ("TBLSTOKFIAT", "FIYAT_TIPI"): {"S": "satış", "A": "alış"},
    ("TBLDOVKUR", "DOVIZ_KODU"): {"USD": "dolar", "EUR": "euro"},
    ("TBLMUHFIS", "HESAP_KODU"): {"600": "yurtiçi satış", "610": "satış iadesi", "153": "ticari mal", "391": "KDV"},
    ("TBLMUHFIS", "BA"): {"B": "borç", "A": "alacak"},
}


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def tables(schema):
    return {table["name"]: table for table in schema["tables"]}


def column(tables, table_name, column_name):
    for column_ in tables[table_name]["columns"]:
        if column_["name"] == column_name:
            return column_
    raise AssertionError(f"{table_name}.{column_name} yok")


def test_the_six_tables_exist_as_data_tables(tables):
    for name in DATA_TABLES:
        table = tables[name]
        assert table["kind"] == "data", name
        assert table["module"].strip(), name
        assert table["description"].strip(), name
        assert table["keywords"], name
        assert all(word.strip() for word in table["keywords"]), name


@pytest.mark.parametrize("table_name", sorted(COLUMNS))
def test_columns_are_the_r2_3_columns_in_order(tables, table_name):
    assert [c["name"] for c in tables[table_name]["columns"]] == COLUMNS[table_name]


def test_every_new_fk_resolves_to_an_existing_column(schema, tables):
    index = {(table["name"], c["name"]) for table in schema["tables"] for c in table["columns"]}
    for name in DATA_TABLES:
        for column_ in tables[name]["columns"]:
            if column_["fk"] is None:
                continue
            target = tuple(column_["fk"].split("."))
            assert target in index, f"{name}.{column_['name']} -> {column_['fk']} yok"


def test_expected_relationships(tables):
    for (table_name, column_name), target in FK.items():
        assert column(tables, table_name, column_name)["fk"] == target


def test_archive_repeats_sthar_columns_and_drops_only_the_invoice_fk(tables):
    sthar, arsiv = tables["TBLSTHAR"]["columns"], tables["TBLSTHAR_ARSIV"]["columns"]
    assert [c["name"] for c in arsiv] == [c["name"] for c in sthar]
    for source, copy in zip(sthar, arsiv):
        assert copy["type"] == source["type"], copy["name"]
        assert copy["values"] == source["values"], copy["name"]
        assert copy["nullable"] == source["nullable"], copy["name"]
        if source["name"] != "FISNO":
            assert copy["fk"] == source["fk"], copy["name"]
    assert column(tables, "TBLSTHAR", "FISNO")["fk"] == "TBLFATUIRS.FATIRS_NO"
    assert column(tables, "TBLSTHAR_ARSIV", "FISNO")["fk"] is None
    assert column(tables, "TBLSTHAR_ARSIV", "FISNO")["nullable"] is True


def test_coded_columns_hold_the_r2_3_codes(tables):
    for (table_name, column_name), codes in CODE_SETS.items():
        assert set(column(tables, table_name, column_name)["values"]) == codes, column_name


def test_coded_meanings_match_r2_3(tables):
    for (table_name, column_name), expected in MEANINGS.items():
        values = column(tables, table_name, column_name)["values"]
        for code, word in expected.items():
            assert word in values[code], (table_name, column_name, code)


def test_money_is_decimal_and_dates_are_date(tables):
    for table_name, column_name in {
        ("TBLSTOKFIAT", "FIYAT"),
        ("TBLDOVKUR", "ALIS"),
        ("TBLDOVKUR", "SATIS"),
        ("TBLKAMPANYA", "INDIRIM_ORANI"),
        ("TBLMUHFIS", "TUTAR"),
    }:
        assert column(tables, table_name, column_name)["type"] == "DECIMAL(18,2)", column_name
    for table_name, column_name in {
        ("TBLSTOKFIAT", "GECERLILIK_TARIHI"),
        ("TBLDOVKUR", "KUR_TARIH"),
        ("TBLKAMPANYA", "BASLANGIC"),
        ("TBLKAMPANYA", "BITIS"),
        ("TBLMUHFIS", "TARIH"),
        ("TBLSTHAR_ARSIV", "STHAR_TARIH"),
    }:
        assert column(tables, table_name, column_name)["type"] == "DATE", column_name
