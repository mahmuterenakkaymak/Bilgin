# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T172: dışa aktarım (PLAN R5-16, Contracts export file).

İddia dosyanın kendisinde: CSV BOM ile açılır, ``;`` ile ayrılır, ondalık virgül taşır ve ayracı,
tırnağı ya da satır sonu olan alanı tırnaklar; XLSX openpyxl ile yeniden açıldığında sayılar sayı
olarak durur. Yol tarafında export bir cevabın yeniden koşumudur: aynı SQL, aynı maske, denetim
günlüğünde ``export:<id>`` satırı - yani indirme ekranın gösterdiğinden fazlası değildir.
"""

import csv
import io
import json
import sqlite3

import openpyxl
import pytest
from fastapi.testclient import TestClient

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.app import asklog
from nl2sql.app.session import open_session
from nl2sql.engine.result import Budget
from nl2sql.report.export import to_csv_bytes, to_xlsx_bytes
from nl2sql.schema_map import build
from nl2sql.web.app import create_app

BOM = chr(0xFEFF)
NL = "\n"
CRLF = "\r\n"

PERSONEL_SQL = "SELECT PERSONEL_KODU, TCKN FROM TBLPERSONEL ORDER BY PERSONEL_KODU"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def db(project):
    """Sentetik ERP'nin kendi dünyası: TCKN ve stok hareketleri gerçek satırlarla dolu."""
    path = project / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


def make_client(db, project, script=None):
    """Kurulu küme, sahte model ve tmp yollar: yol testlerinin dünyası (R5-22)."""
    session = open_session(
        dataset="synthetic_erp",
        llm="fake",
        db_path=db,
        index_dir=project / "index",
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
        client_factory=(lambda mode: fake.FakeLLM(script)) if script else None,
    )
    client = TestClient(
        create_app(session, saved_path=project / "bilgin.db", static_dir=project / "static")
    )
    return client, session


def ask(client, question, mode="full"):
    body = client.post("/api/ask", json={"question": question, "mode": mode}).json()
    assert body["status"] == "answered", body["error"]
    return body["audit_id"]


def golden_line(session, qid):
    return next(item for item in session.dataset.golden() if item["id"] == qid)


def golden_rows(session, line):
    return session.executor.execute(line["sql"], Budget(max_rows=config.EXPORT_MAX_ROWS), "test")


def csv_text(content: bytes) -> str:
    text = content.decode("utf-8")
    assert text.startswith(BOM), "Excel UTF-8'i ancak BOM'u görünce tanır"
    return text[len(BOM) :]


def csv_rows(content: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(csv_text(content)), delimiter=";"))


def workbook(content: bytes):
    return openpyxl.load_workbook(io.BytesIO(content)).active


def raw_tckn(db) -> list[str]:
    """Fişörtmedeki ham kimlik numaraları: hiçbirinin dışa çıkmadığı bunlarla denetlenir."""
    with sqlite3.connect(db) as conn:
        return [row[0] for row in conn.execute("SELECT TCKN FROM TBLPERSONEL WHERE TCKN IS NOT NULL")]


# ------------------------------------------------------------------ dosyanın kendisi


def test_csv_bytes_use_bom_semicolon_and_decimal_comma():
    data = to_csv_bytes(["MÜŞTERİ", "TUTAR", "NOT"], [["A;B", 1250.5, None], ['C"D', 3, "iki" + NL + "satır"]])

    text = data.decode("utf-8")
    assert text.startswith(BOM) and CRLF in text and ";" in text
    lines = text[len(BOM) :].split(CRLF)
    assert lines[0] == "MÜŞTERİ;TUTAR;NOT"
    assert lines[1] == '"A;B";1250,5;', "ayraç alanı tırnaklar, ondalık virgül, NULL boş alan"
    assert lines[2] == '"C""D";3;"iki' + NL + 'satır"', "tırnak iki katına çıkar, satır sonu alanın içinde kalır"
    assert lines[3] == ""


def test_xlsx_reopens_with_numeric_cells_and_a_bold_header():
    data = to_xlsx_bytes(["KOD", "ADET", "TUTAR", "NOT"], [["A", 3, 12.75, None]])

    sheet = workbook(data)
    assert sheet.title == "Sonuç"
    assert [cell.value for cell in sheet[1]] == ["KOD", "ADET", "TUTAR", "NOT"]
    assert all(cell.font.bold for cell in sheet[1])
    assert [sheet[f"{column}2"].value for column in "ABCD"] == ["A", 3, 12.75, None]
    assert [sheet[f"{column}2"].data_type for column in "ABC"] == ["s", "n", "n"], "sayı sayı olarak yazar"


# ------------------------------------------------------------------ yol: cevabın dosyası


def test_csv_export_of_an_answer_equals_the_golden_rows(db, project):
    client, session = make_client(db, project)
    line = golden_line(session, "Q02")
    audit_id = ask(client, line["question"])
    golden = golden_rows(session, line)

    response = client.get(f"/api/export/{audit_id}.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == f'attachment; filename="bilgin_{audit_id}.csv"'
    rows = csv_rows(response.content)
    assert rows[0] == golden.columns
    assert [row[:2] for row in rows[1:]] == [[str(value) for value in row[:2]] for row in golden.rows]
    assert [float(row[2].replace(",", ".")) for row in rows[1:]] == [float(row[2]) for row in golden.rows]


def test_xlsx_export_of_an_answer_equals_the_golden_rows(db, project):
    client, session = make_client(db, project)
    line = golden_line(session, "Q02")
    audit_id = ask(client, line["question"])
    golden = golden_rows(session, line)

    response = client.get(f"/api/export/{audit_id}.xlsx")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert response.headers["content-disposition"] == f'attachment; filename="bilgin_{audit_id}.xlsx"'
    sheet = workbook(response.content)
    assert sheet.title == "Sonuç"
    assert [[cell.value for cell in row] for row in sheet.iter_rows()] == (
        [golden.columns] + [list(row) for row in golden.rows]
    )


def test_a_tckn_export_carries_only_the_mask(db, project):
    client, _ = make_client(db, project, script=fake.wrong_sql(PERSONEL_SQL))
    audit_id = ask(client, "Personellerin kimlik numaraları ne?")

    csv_body = client.get(f"/api/export/{audit_id}.csv").content
    column = [row[1] for row in csv_rows(csv_body)][1:]
    cells = [cell.value for cell in workbook(client.get(f"/api/export/{audit_id}.xlsx").content)["B"][1:]]

    assert column and cells, "hem CSV hem Excel dolu satırlar taşımalı"
    assert all(value.startswith("*******") for value in column + cells)
    for raw in raw_tckn(db):
        assert raw not in csv_text(csv_body)
        assert raw not in column + cells


def test_an_export_leaves_its_own_audit_line(db, project):
    client, session = make_client(db, project)
    audit_id = ask(client, golden_line(session, "Q01")["question"])

    assert client.get(f"/api/export/{audit_id}.csv").status_code == 200

    lines = [json.loads(line) for line in (project / "audit.jsonl").read_text(encoding="utf-8").splitlines() if line]
    assert f"export:{audit_id}" in {line["source"] for line in lines}


# ------------------------------------------------------------------ yol: redler


def test_an_unknown_audit_id_has_nothing_to_export(db, project):
    client, _ = make_client(db, project)

    response = client.get("/api/export/yokboylebir1.csv")

    assert response.status_code == 404
    assert response.json() == {"detail": "Bu sorunun kaydı bulunamadı."}


def test_a_failed_ask_refuses_to_export(db, project):
    client, _ = make_client(db, project, script=fake.never_submit())
    body = client.post("/api/ask", json={"question": "Ürünlerin listesi?", "mode": "full"}).json()
    assert body["status"] == "failed"

    response = client.get(f"/api/export/{body['audit_id']}.xlsx")

    assert response.status_code == 409
    assert response.json() == {"detail": "Yalnızca cevaplanmış bir soru dışa aktarılabilir."}


def test_an_ask_of_another_dataset_refuses_to_export(db, project):
    client, _ = make_client(db, project)
    asklog.record_ask(
        {"audit_id": "baskabirkay1", "status": "answered", "sql": "SELECT 1", "dataset": "wwi"},
        project / "asks.jsonl",
    )

    response = client.get("/api/export/baskabirkay1.csv")

    assert response.status_code == 409
    assert response.json() == {"detail": "Bu kayıt başka bir veri kümesine ait."}
