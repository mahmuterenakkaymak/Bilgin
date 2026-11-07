# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T247: iki kökte veri kümeleri (PLAN R6-11) — ad araması, kök etiketi, ad çakışması.

``load_dataset`` adı artık önce ``datasets_dir()`` sonra ``real_datasets_dir()`` köklerinde
arar: ekrandan yüklenen gerçek kümeler kodun yanındaki ``real_datasets/`` klasörüne yazılır,
yani üretilen kümelerle aynı adla anılır. ``all_datasets`` iki kökeyi tek listede toplar ve
``root`` alanı kümenin nereden geldiğini söy; ``name_taken`` şablon doğrulamasının çakışmayı
yüklemeden görmesi için ``dataset.json``'a bakmaz.
"""

import json

import pytest

from nl2sql import config
from nl2sql.datasets import DatasetError, all_datasets, list_datasets, load_dataset, name_taken

ENV_VARS = ["NL2SQL_DATASETS_DIR", "NL2SQL_REAL_DATASETS_DIR"]

MINI_DOC = {
    "name": "mini",
    "as_of": "2026-01-31",
    "builder": "builder.py:build_db",
    "generator": "builder.py:generate",
    "references": "builder.py:REFERENCES",
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def write_dataset(root, name: str, **extra) -> None:
    """A folder that loads: only ``dataset.json`` is needed, code refs resolve on use."""
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "dataset.json").write_text(
        json.dumps({**MINI_DOC, "name": name, **extra}, ensure_ascii=False), encoding="utf-8"
    )


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """Two empty roots wired to the env vars the readers use."""
    synthetic, real = tmp_path / "datasets", tmp_path / "real"
    synthetic.mkdir()
    real.mkdir()
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(synthetic))
    monkeypatch.setenv("NL2SQL_REAL_DATASETS_DIR", str(real))
    return synthetic, real


# ------------------------------------------------------------------ the second root


def test_real_root_dataset_loads_by_name(roots):
    _, real = roots
    write_dataset(real, "gercek", connection="mssql", display_name="Gerçek müşteri")
    dataset = load_dataset("gercek")
    assert dataset.root == real / "gercek"
    assert dataset.connection == "mssql"
    assert dataset.display_name == "Gerçek müşteri"


def test_first_root_wins_a_clash(roots):
    synthetic, real = roots
    write_dataset(synthetic, "kopya", display_name="Üretilen")
    write_dataset(real, "kopya", display_name="Gerçek")
    assert load_dataset("kopya").display_name == "Üretilen"


def test_explicit_root_stays_a_single_root(roots):
    synthetic, real = roots
    write_dataset(real, "gercek")
    assert load_dataset("gercek", root=real).root == real / "gercek"
    with pytest.raises(DatasetError) as error:
        load_dataset("gercek", root=synthetic)
    assert str(error.value) == "Bilinmeyen veri kümesi: gercek (bilinenler: )"


def test_unknown_name_lists_both_roots(roots):
    synthetic, real = roots
    write_dataset(synthetic, "bbb")
    write_dataset(real, "aaa")
    with pytest.raises(DatasetError) as error:
        load_dataset("yok")
    assert str(error.value) == "Bilinmeyen veri kümesi: yok (bilinenler: aaa, bbb)"


# ------------------------------------------------------------------ all_datasets


def test_all_datasets_lists_both_roots_sorted(roots):
    synthetic, real = roots
    write_dataset(synthetic, "zeta", display_name="Z", connection="sqlite")
    write_dataset(real, "alfa", display_name="A", connection="mssql")
    assert all_datasets() == [
        {
            "name": "alfa",
            "display_name": "A",
            "connection": "mssql",
            "root": "real_datasets",
            "path": str(real / "alfa"),
        },
        {
            "name": "zeta",
            "display_name": "Z",
            "connection": "sqlite",
            "root": "datasets",
            "path": str(synthetic / "zeta"),
        },
    ]


def test_all_datasets_reports_a_clash_once(roots):
    synthetic, real = roots
    write_dataset(synthetic, "kopya", display_name="Üretilen")
    write_dataset(real, "kopya", display_name="Gerçek")
    items = all_datasets()
    assert [item["root"] for item in items] == ["datasets"]
    assert items[0]["display_name"] == "Üretilen"


def test_all_datasets_skips_a_folder_without_definition(roots):
    synthetic, real = roots
    write_dataset(synthetic, "mini")
    (real / "bos_klasor").mkdir()
    assert [item["name"] for item in all_datasets()] == ["mini"]
    assert list_datasets(real) == []


# ------------------------------------------------------------------ name_taken


def test_name_taken_accepts_a_bare_folder(roots):
    synthetic, real = roots
    assert not name_taken("yeni")
    (real / "yeni").mkdir()  # dataset.json yok: R6-15 yine de adı dolu saymalı
    assert name_taken("yeni")
    assert not name_taken("baska")


def test_name_taken_sees_the_first_root_too(roots):
    synthetic, _ = roots
    (synthetic / "yeni").mkdir()
    assert name_taken("yeni")
    assert not name_taken("baska")


# ------------------------------------------------------------------ the repo's own roots


def test_repo_wwi_real_loads_by_name():
    dataset = load_dataset("wwi_real")
    assert dataset.root == config.REAL_DATASETS_DIR / "wwi_real"
    assert dataset.connection == "mssql"


def test_repo_lists_both_kinds():
    items = {item["name"]: item for item in all_datasets()}
    assert items[config.DEFAULT_DATASET]["root"] == "datasets"
    assert items["wwi_real"]["root"] == "real_datasets"
    assert name_taken("wwi_real")
