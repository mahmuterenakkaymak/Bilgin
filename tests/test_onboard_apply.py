# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T250: önizleme diskte bekler, uygulandığında klasör olur (PLAN R6-16).

Bir şablon yüklemenin iki yüzü var: ekranda bekleyen kontrol raporu, diskte ise sıfırdan doğan bir
veri kümesi klasörü. Testler ikisini de kanıtlar - yedi dosya, `datasets.load_dataset`in okuduğu
tanım, kişisel veri/kapalı işaretlerini koruyan şema, parolasız giriş betiği, kim ve kaç tane
söyleyen günlük satırı - ve hiçbirinin var olan bir kümenin tek baytını oynamadığını gösterir.
İndeks işi gerçek `build-index` yoludur: sahte embedder ile biter, bozuk olanla Türkçe cümle bırakır.
"""

import hashlib
import json
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bilgin import config, datasets
from bilgin.schema_map import onboard
from bilgin.schema_map.template import filled_example_workbook
from bilgin.schema_map.template_import import read_template, validate

REPO = Path(__file__).resolve().parents[1]
NAME = "deneme_kume"
TABLE = "SATIS.FATURA"
FOLDER_FILES = [
    "dataset.json",
    "golden.jsonl",
    "profile.json",
    "readonly_login.sql",
    "real.py",
    "rules.json",
    "schema.json",
]
RULE = {
    "id": "fatura_tutari",
    "term": "Fatura tutarı",
    "synonyms": ["ciro", "satış tutarı"],
    "definition": "Bir faturanın KDV hariç toplamı; iade faturaları eksi olarak sayılır.",
    "sql_hint": "SUM(Fatura.Tutar)",
    "tables": ["Satis.Fatura"],
    "markers": [],
    "synonyms_en": ["invoice amount", "revenue"],  # Updated automatically: T415/R8-13 changed this contract.
}


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """İki kök, iki günlük ve `outputs`un ROOT'u tmp'de: repo ile `data/` hiç anılmaz."""
    (tmp_path / "datasets").mkdir()
    (tmp_path / "real_datasets").mkdir()
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(tmp_path / "datasets"))
    monkeypatch.setenv("BILGIN_REAL_DATASETS_DIR", str(tmp_path / "real_datasets"))
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "MAP_PREVIEWS_DIR", tmp_path / "map_previews")
    monkeypatch.setattr(config, "MAP_CHANGES_LOG", tmp_path / "logs" / "map_changes.jsonl")
    return tmp_path


def example_result(tmp_path, name: str = NAME) -> dict:
    """Yükleme raporunun kendisi: okuma + doğrulama, yani `/preview`ın kaydettiği nesne."""
    path = tmp_path / f"{name}.xlsx"
    path.write_bytes(filled_example_workbook(name))
    read = read_template(str(path))
    errors, warnings, db_check = validate(read)
    assert errors == []
    return {
        "dataset": read["dataset"],
        "counts": read["counts"],
        "errors": errors,
        "warnings": warnings,
        "db_check": db_check,
        "schema": read["schema"],
        "rules": read["rules"],
    }


def saved_preview(tmp_path, name: str = NAME) -> dict:
    return onboard.load_preview(save_example(tmp_path, name))


def save_example(tmp_path, name: str = NAME) -> str:
    return onboard.save_preview(example_result(tmp_path, name), "eren", "sablon.xlsx")


def apply_example(tmp_path, name: str = NAME) -> Path:
    return onboard.apply_preview(saved_preview(tmp_path, name), "eren")


def digest(folder: Path) -> dict:
    """Klasördeki her dosyanın sağlama toplamı: tek bayt oynasa anahtar değişir."""
    return {
        str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def change_lines() -> list[dict]:
    path = Path(config.MAP_CHANGES_LOG)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def wait_for_job(jobs: onboard.IndexJobs, preview_id: str, timeout: float = 120.0) -> dict:
    """Aşama bir daha değişmeyecek an: iş bitti ya da düştü."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = jobs.status(preview_id)
        if status["phase"] in ("done", "failed"):
            return status
        time.sleep(0.02)
    raise AssertionError(f"iş bitmedi: {jobs.status(preview_id)}")


# ------------------------------------------------------------------ önizleme


def test_the_upload_writes_the_preview_and_nothing_else(tmp_path, roots):
    preview_id = save_example(tmp_path)

    assert [path.name for path in Path(config.MAP_PREVIEWS_DIR).iterdir()] == [f"{preview_id}.json"]
    assert list(Path(config.real_datasets_dir()).iterdir()) == []
    assert not Path(config.MAP_CHANGES_LOG).exists()

    record = read_json(Path(config.MAP_PREVIEWS_DIR) / f"{preview_id}.json")
    assert record["preview_id"] == preview_id
    assert record["username"] == "eren"
    assert record["filename"] == "sablon.xlsx"
    assert record["dataset"]["name"] == NAME
    assert record["counts"]["tables"] == 1
    assert record["schema"]["tables"][0]["name"] == TABLE
    assert record["rules"] == [RULE]


def test_a_preview_loads_whose_clock_ran_out_and_is_purged(tmp_path, roots):
    preview_id = save_example(tmp_path)
    assert onboard.load_preview(preview_id)["preview_id"] == preview_id

    later = datetime.now(timezone.utc) + timedelta(minutes=config.MAP_PREVIEW_TTL_MIN + 1)
    assert onboard.load_preview(preview_id, now=later) is None
    assert not (Path(config.MAP_PREVIEWS_DIR) / f"{preview_id}.json").exists()


def test_a_purge_keeps_the_preview_that_is_still_in_time(tmp_path, roots):
    first = save_example(tmp_path, "birinci_kume")
    second = save_example(tmp_path, "ikinci_kume")

    assert onboard.load_preview(first) is not None
    assert onboard.load_preview(second) is not None
    assert len(list(Path(config.MAP_PREVIEWS_DIR).iterdir())) == 2


def test_a_stranger_is_not_a_preview_id(tmp_path, roots):
    save_example(tmp_path)

    for foreign in ("", "..\\..\\sablon", "Z" * 32, "a" * 31):
        assert onboard.load_preview(foreign) is None


# ------------------------------------------------------------------ uygulama


def test_applying_the_example_writes_every_file(tmp_path, roots):
    folder = apply_example(tmp_path)

    assert folder == Path(config.real_datasets_dir()) / NAME
    assert sorted(path.name for path in folder.iterdir()) == FOLDER_FILES
    assert (folder / "golden.jsonl").read_text(encoding="utf-8") == ""
    assert read_json(folder / "profile.json") == {"name": NAME, "pairs": []}


def test_the_folder_loads_as_a_dataset_of_its_own(tmp_path, roots):
    apply_example(tmp_path)
    ds = datasets.load_dataset(NAME)

    assert ds.display_name == NAME
    assert ds.connection == "sqlite"
    assert ds.as_of == "2026-10-01"
    assert ds.seed == 42
    assert ds.db_path == roots / "data" / f"{NAME}.db"
    assert ds.mssql_script == roots / "db" / "mssql" / f"build_{NAME}.sql"
    assert ds.index_dir == roots / "index" / NAME
    assert ds.eval_out == roots / "eval_out" / NAME
    assert ds.fake_fallback_sql == f"SELECT COUNT(*) AS KAYIT_SAYISI FROM {TABLE}"
    # real.py'nin kendisi de yüklenir: küme kurulmaz, üretilmez, referansı veritabanıdır.
    assert ds.references() == {}


def test_the_schema_keeps_the_personal_and_closed_marks(tmp_path, roots):
    apply_example(tmp_path)
    tables = datasets.load_dataset(NAME).schema()["tables"]

    assert [table["name"] for table in tables] == [TABLE]
    assert tables[0]["kind"] == "data"
    columns = {column["name"]: column for column in tables[0]["columns"]}
    assert columns["YETKILIADI"]["pii"] == "person_name"
    assert columns["ICNOT"]["deny"] is True


def test_the_rules_sheet_lands_in_rules_json(tmp_path, roots):
    folder = apply_example(tmp_path)

    assert read_json(folder / "rules.json") == {"rules": [RULE]}
    assert datasets.load_dataset(NAME).rules() == [RULE]


def test_the_login_script_carries_no_password(tmp_path, roots):
    sql = (apply_example(tmp_path) / "readonly_login.sql").read_text(encoding="utf-8")

    assert f"[bilgin_{NAME}_ro]" in sql
    assert "PASSWORD = '__DEGISTIR__'" in sql
    assert "YETKILIADI" in sql and "ICNOT" in sql


def test_the_change_log_line_names_the_user_and_the_counts(tmp_path, roots):
    counts = example_result(tmp_path)["counts"]
    apply_example(tmp_path)

    line = change_lines()[-1]
    assert line["username"] == "eren"
    assert line["name"] == NAME
    assert line["counts"] == counts
    assert datetime.fromisoformat(line["ts"])


def test_a_taken_name_is_refused_without_touching_the_folder(tmp_path, roots):
    preview = saved_preview(tmp_path)
    folder = onboard.apply_preview(preview, "eren")
    before = digest(folder)

    with pytest.raises(FileExistsError):
        onboard.apply_preview(preview, "eren")

    assert digest(folder) == before


def test_a_failed_write_removes_only_the_folder_it_created(tmp_path, roots, monkeypatch):
    def broken(schema, login):
        raise OSError("disk yok")

    monkeypatch.setattr(onboard, "readonly_login_sql", broken)

    with pytest.raises(OSError):
        apply_example(tmp_path)

    assert not (Path(config.real_datasets_dir()) / NAME).exists()
    assert not Path(config.MAP_CHANGES_LOG).exists()


def test_an_apply_leaves_every_existing_dataset_byte_identical(tmp_path, roots):
    shutil.copytree(REPO / "datasets" / "synthetic_erp", roots / "datasets" / "synthetic_erp")
    shutil.copytree(REPO / "real_datasets" / "wwi_real", roots / "real_datasets" / "wwi_real")
    before = {
        "synthetic_erp": digest(roots / "datasets" / "synthetic_erp"),
        "wwi_real": digest(roots / "real_datasets" / "wwi_real"),
    }

    apply_example(tmp_path)

    assert digest(roots / "datasets" / "synthetic_erp") == before["synthetic_erp"]
    assert digest(roots / "real_datasets" / "wwi_real") == before["wwi_real"]


# ------------------------------------------------------------------ indeks işi


def test_the_index_job_finishes_with_the_fake_embedder(tmp_path, roots):
    preview = saved_preview(tmp_path)
    onboard.apply_preview(preview, "eren")
    jobs = onboard.IndexJobs()

    jobs.start(preview["preview_id"], NAME, "fake")
    status = wait_for_job(jobs, preview["preview_id"])

    assert status["name"] == NAME
    assert status["phase"] == "done"
    assert status["message"] is None
    assert (datasets.load_dataset(NAME).index_dir / "meta.json").is_file()


def test_a_broken_embedder_fails_the_job_with_a_sentence(tmp_path, roots):
    preview = saved_preview(tmp_path)
    onboard.apply_preview(preview, "eren")
    jobs = onboard.IndexJobs()

    jobs.start(preview["preview_id"], NAME, "bozuk")
    status = wait_for_job(jobs, preview["preview_id"])

    assert status["preview_id"] == preview["preview_id"]
    assert status["phase"] == "failed"
    assert "Bilinmeyen embedder" in status["message"]


def test_a_job_that_never_ran_has_no_status(tmp_path, roots):
    assert onboard.IndexJobs().status("a" * 32) is None
