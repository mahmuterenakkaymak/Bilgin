# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T123: veri kümesi yükleyicisi (PLAN R4-1, R4-3) — klasör okuma, kod gönderimleri, hatalar.

``synthetic_erp`` gerçek klasöründen yüklenir ve yolları ``config`` ile aynı çıkmak zorundadır:
R4-2 taşımayı yalnızca yol değiştirerek yaptığı için config'in varsayılanları hâlâ aynı
dosyaları gösteriyor. Mini küme ``tmp_path`` içinde kurulur; ``builder.py`` dosya gönderimiyle
çözülür ve ``outputs`` yazılmadığı için R4-3 varsayılanları ``config.ROOT``'a göre hesaplanır
(disk'e hiçbir çıktı yazılmaz, sadece yol üretilir; build_db testte açık yol verilir).
"""

import dataclasses
import json
from pathlib import Path

import pytest

from eval import reference
from bilgin import config
from bilgin.agent import fake
from bilgin.datasets import DatasetError, list_datasets, load_dataset
from bilgin.eval import runner

ENV_VARS = ["BILGIN_DATASETS_DIR"]

MINI_DOC = {
    "name": "mini",
    "as_of": "2026-01-31",
    "builder": "builder.py:build_db",
    "generator": "builder.py:generate",
    "references": "builder.py:REFERENCES",
}
MINI_SCHEMA = {
    "tables": [
        {
            "name": "TBLX",
            "columns": [{"name": "SEED", "type": "INT"}, {"name": "ADI", "type": "NVARCHAR(50)"}],
        }
    ]
}
MINI_RULES = {"rules": [{"term": "ciro", "text": "tohumların toplamı", "sql_hint": "SUM(SEED)"}]}
MINI_GOLDEN = '{"id": "Q01", "question": "tohum kaç", "sql": "SELECT SUM(SEED) FROM TBLX"}\n'

# __name__ üzerinden modül adını da döner: dosya gönderiminin hangi modül adıyla yüklendiği
# sözleşmenin bir parçası (bilgin_dataset_<name>_<stem>), başka türlü dışarıdan okunamıyor.
MINI_BUILDER = '''"""Mini veri kümesi: builder, generator ve referans tek dosyada."""

from pathlib import Path


def build_db(seed, db_path, sql_path):
    Path(db_path).write_text(f"db:{seed}", encoding="utf-8")
    Path(sql_path).write_text(f"sql:{seed}", encoding="utf-8")
    return "checksum"


def generate(seed):
    return {"TBLX": [{"SEED": seed, "MODULE": __name__}]}


REFERENCES = {"Q01": __name__}
'''


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def write_mini(root: Path, doc: dict | None = None) -> Path:
    """A complete dataset folder under ``root``: dataset.json + builder.py + its data files."""
    folder = root / "mini"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "dataset.json").write_text(
        json.dumps(doc if doc is not None else MINI_DOC, ensure_ascii=False), encoding="utf-8"
    )
    (folder / "builder.py").write_text(MINI_BUILDER, encoding="utf-8")
    (folder / "schema.json").write_text(json.dumps(MINI_SCHEMA), encoding="utf-8")
    (folder / "rules.json").write_text(json.dumps(MINI_RULES), encoding="utf-8")
    (folder / "golden.jsonl").write_text(MINI_GOLDEN, encoding="utf-8")
    return folder


# ------------------------------------------------------------------ the real dataset


def test_synthetic_erp_paths_are_the_config_paths():
    dataset = load_dataset("synthetic_erp")
    assert dataset.name == config.DEFAULT_DATASET
    for name, path in (
        ("schema_path", config.SCHEMA_PATH),
        ("rules_path", config.RULES_PATH),
        ("profile_path", config.PROFILE_PATH),
        ("golden_path", config.GOLDEN_PATH),
        ("traps_path", config.TRAPS_PATH),
        ("db_path", config.DB_PATH),
        ("mssql_script", config.MSSQL_SCRIPT),
        ("index_dir", config.INDEX_DIR),
        ("eval_out", config.EVAL_OUT),
    ):
        assert getattr(dataset, name) == path, name
    assert dataset.root == config.SCHEMA_PATH.parent


def test_synthetic_erp_fields_match_dataset_json():
    dataset = load_dataset("synthetic_erp")
    assert dataset.display_name == "Sentetik ERP"  # Updated 2026-10-26 (Eren: "otomatik olsun"): T357, no product name
    assert dataset.dialect == "tsql"
    assert dataset.connection == "sqlite"
    assert dataset.default_schema == "dbo"
    assert dataset.as_of == config.AS_OF
    assert dataset.seed == config.SEED
    assert dataset.fake_fallback_sql == fake.FALLBACK_SQL


def test_synthetic_erp_references_are_the_python_truth():
    assert load_dataset("synthetic_erp").references() is reference.REFERENCES


def test_synthetic_erp_golden_gets_the_runner_defaults():
    golden = load_dataset("synthetic_erp").golden()
    assert golden == runner.load_golden()
    assert all(set(runner.GOLDEN_LIST_FIELDS) <= set(line) for line in golden)


def test_synthetic_erp_schema_and_rules_load():
    dataset = load_dataset("synthetic_erp")
    assert dataset.schema()["tables"]
    assert dataset.rules()


def test_dataset_is_frozen():
    dataset = load_dataset("synthetic_erp")
    with pytest.raises(dataclasses.FrozenInstanceError):
        dataset.seed = 7


# ------------------------------------------------------------------ a folder-built dataset


def test_file_ref_dataset_gets_the_run4_defaults(tmp_path):
    write_mini(tmp_path)
    dataset = load_dataset("mini", root=tmp_path)
    assert dataset.db_path == config.ROOT / "data" / "mini.db"
    assert dataset.mssql_script == config.ROOT / "db" / "mssql" / "build_mini.sql"
    assert dataset.index_dir == config.ROOT / "index" / "mini"
    assert dataset.eval_out == config.ROOT / "eval_out" / "mini"
    assert dataset.traps_path is None
    assert dataset.seed == 42
    assert dataset.display_name == "mini"
    assert dataset.dialect == "tsql"
    assert dataset.connection == "sqlite"
    assert dataset.default_schema is None
    assert dataset.fake_fallback_sql == "SELECT SUM(SEED) FROM TBLX"
    assert dataset.schema()["tables"][0]["name"] == "TBLX"
    assert dataset.rules()[0]["synonyms"] == []
    assert dataset.golden()[0]["tags"] == []


def test_file_ref_generator_and_builder(tmp_path):
    write_mini(tmp_path)
    dataset = load_dataset("mini", root=tmp_path)
    assert dataset.generate() == {"TBLX": [{"SEED": 42, "MODULE": "bilgin_dataset_mini_builder"}]}
    assert dataset.generate(seed=7) == {"TBLX": [{"SEED": 7, "MODULE": "bilgin_dataset_mini_builder"}]}
    assert dataset.references() == {"Q01": "bilgin_dataset_mini_builder"}
    db, sql = tmp_path / "out.db", tmp_path / "out.sql"
    assert dataset.build_db(db_path=db, sql_path=sql) == "checksum"
    assert db.read_text(encoding="utf-8") == "db:42"
    assert dataset.build_db(seed=3, db_path=db, sql_path=sql) == "checksum"
    assert sql.read_text(encoding="utf-8") == "sql:3"


def test_code_references_resolve_only_on_use(tmp_path):
    write_mini(tmp_path, dict(MINI_DOC, generator="yok.modul:generate"))
    dataset = load_dataset("mini", root=tmp_path)
    with pytest.raises(ModuleNotFoundError):
        dataset.generate()


# ------------------------------------------------------------------ listing and errors


def test_list_datasets_sorts_and_requires_dataset_json(tmp_path):
    for name in ("bbb", "aaa"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "dataset.json").write_text(json.dumps({"name": name}), encoding="utf-8")
    (tmp_path / "klasor").mkdir()
    (tmp_path / "dataset.json").write_text("{}", encoding="utf-8")
    assert list_datasets(tmp_path) == ["aaa", "bbb"]


def test_list_datasets_without_a_folder(tmp_path):
    assert list_datasets(tmp_path / "yok") == []


def test_repo_folder_holds_the_default_dataset():
    assert config.DEFAULT_DATASET in list_datasets()


def test_unknown_dataset_lists_the_known_ones(tmp_path):
    for name in ("aaa", "bbb"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "dataset.json").write_text(json.dumps({"name": name}), encoding="utf-8")
    with pytest.raises(DatasetError) as error:
        load_dataset("yok", root=tmp_path)
    assert str(error.value) == "Bilinmeyen veri kümesi: yok (bilinenler: aaa, bbb)"


def test_unknown_dataset_in_the_repo_folder():
    with pytest.raises(DatasetError) as error:
        load_dataset("yok")
    assert str(error.value).startswith("Bilinmeyen veri kümesi: yok (bilinenler: ")
    assert config.DEFAULT_DATASET in str(error.value)


@pytest.mark.parametrize("key", ["name", "as_of", "builder", "generator", "references"])
def test_missing_key_names_the_key_and_the_file(tmp_path, key):
    doc = dict(MINI_DOC)
    del doc[key]
    write_mini(tmp_path, doc)
    with pytest.raises(DatasetError) as error:
        load_dataset("mini", root=tmp_path)
    assert f"'{key}'" in str(error.value)
    assert str(tmp_path / "mini" / "dataset.json") in str(error.value)


# ------------------------------------------------------------------ the datasets dir


def test_datasets_dir_env_is_read_at_call_time(monkeypatch, tmp_path):
    write_mini(tmp_path)
    assert config.DEFAULT_DATASET in list_datasets()
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(tmp_path))
    assert list_datasets() == ["mini"]
    assert load_dataset("mini").root == tmp_path / "mini"
