# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T427: M27 entegrasyonu — dilin kendisi uçtan uca, elle kurulmuş tek parça olmadan (PLAN R8-5..R8-12).

Kapı gerçek ``create_app``, hesaplar gerçek ``UserStore``, oturum gerçek ``open_session``, model
``cli.make_client("fake")``ın iki dilin altın kaydını da oynatan hâli, küme gerçek ``wwi``. İddia
zinciri bir kişinin günüdür: yönetici ``PUT /api/auth/me``le arayüzünü İngilizceye çevirir, İngilizce
altın sorunun cevabı İngilizcedir, boş sorunun reddi İngilizcedir, indirdiği şablon İngilizcedir;
aynı şablonu doldurur, önizler ve yeni bir küme olarak uygular. Aynı içerik Türkçe şablona yazılıp
uygulandığında diskte doğan ``schema.json`` ve ``rules.json`` bayt bayt aynıdır - dil yalnız arayüzün
kostümüdür. Tercih yapmamış bir kişi aynı uygulamada bugünkü Türkçe metinleri okumaya devam eder ve
``eval --lang en`` İngilizce altın kümeyi koşar.
"""

from __future__ import annotations

import base64
import io
import json
import time
from types import SimpleNamespace

import openpyxl
import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from nl2sql import config, datasets
from nl2sql.app.session import open_session
from nl2sql.auth.store import UserStore
from nl2sql.cli import main as cli
from nl2sql.datasets import load_dataset
from nl2sql.i18n import t
from nl2sql.i18n.detect import TURKISH_LETTERS
from nl2sql.schema_map import template
from nl2sql.web.app import create_app

WWI = load_dataset("wwi")
E01 = next(line for line in WWI.golden("en") if line["id"] == "E01")

PAROLA = "Bilgin2026!m27"
ADMIN, ADMIN_EN, USER = "yonetici", "yonetici_en", "kullanici"
TEMPLATE_URL = "/api/schema-map/template.xlsx"
EN_DATASET, TR_DATASET = "harita_en", "harita_tr"

# Şablonun doldurulan dört sayfası: rol adı -> ``LABELS["sheets"]`` indeksi ve başlık anahtarı.
ROLES = {"dataset": 1, "tables": 2, "columns": 3, "rules": 4}
HEADER_KEYS = {
    "dataset": "dataset_headers",
    "tables": "table_headers",
    "columns": "column_headers",
    "rules": "rule_headers",
}

# İçerik veridir, çeviri değil: iki dile de aynı satırlar yazılır, fark yalnız başlıklardadır.
TABLE = "Satis.Fatura"
DATASET_TAIL = ("Satis Faturalari", "sqlite", "dbo", "2026-10-01")
TABLE_ROW = (
    TABLE,
    "Satis",
    "Header row of a sales invoice; every row is one invoice.",
    "invoice, sales",
)
COLUMN_ROWS = (
    ("FaturaID", "INT", "Number of the invoice", "", "", False, "", False),
    ("Tutar", "DECIMAL(18,2)", "Invoice amount without VAT", "", "", False, "", True),
    ("IcNot", "NVARCHAR(250)", "Internal note of the invoice", "", "", True, "", True),
    ("CariKod", "NVARCHAR(20)", "Customer code of the invoice", "", "", False,
     f"{TABLE}.FaturaID", False),
)
RULE_ROW = (
    "fatura_tutari",
    "Invoice amount",
    "revenue, sales amount",
    "Total of an invoice without VAT.",
    "SUM(Fatura.Tutar)",
    TABLE,
    "invoice amount, revenue",
)


# ------------------------------------------------------------------ dünyanın parçaları


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Modülün dünyası bir kez: wwi'nin kendi builder'ının tmp'de kurduğu dosya ve tek kapı.

    ``config.ROOT`` tmp'de, yani kümenin ``data/``, ``index/`` ve ``eval_out/`` çıktıları da oraya
    düşer; ``real_datasets`` kökü ayrıca çevrilir ki şablondan doğan kümeler repoya değmesin.
    Kabukta ambiyans duran bağlantı ve dil değişkenleri silinir (R7-29, R8-5).
    """
    root = tmp_path_factory.mktemp("m27")
    (root / "real_datasets").mkdir()
    mp = MonkeyPatch()
    mp.setattr(config, "ROOT", root)
    mp.delenv("NL2SQL_DATASETS_DIR", raising=False)
    mp.setenv("NL2SQL_REAL_DATASETS_DIR", str(root / "real_datasets"))
    mp.setattr(config, "MAP_PREVIEWS_DIR", root / "map_previews")
    mp.setattr(config, "MAP_CHANGES_LOG", root / "logs" / "map_changes.jsonl")
    mp.delenv("NL2SQL_MSSQL_CONN", raising=False)
    mp.delenv("NL2SQL_BACKEND", raising=False)
    mp.delenv("NL2SQL_LANG", raising=False)
    assert cli.build_database(dataset="wwi") == 0

    users = UserStore(root / "bilgin.db")
    users.add_user(ADMIN, PAROLA, "admin")
    users.add_user(ADMIN_EN, PAROLA, "admin")
    users.add_user(USER, PAROLA, "user")
    app = create_app(
        open_session(dataset="wwi", llm="fake"),
        saved_path=root / "bilgin.db",
        static_dir=root / "static",
        users=users,
    )
    try:
        yield SimpleNamespace(root=root, app=app)
    finally:
        mp.undo()


def girisli(app, username: str) -> TestClient:
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"username": username, "password": PAROLA})
    assert response.status_code == 200, f"{username} giriş yapamadı: {response.status_code}"
    return client


def ingiliz_yonetici(world) -> TestClient:
    """Günün ilk hareketi: yönetici kendi dilini ``PUT /api/auth/me``le İngilizceye çevirir."""
    client = girisli(world.app, ADMIN_EN)
    assert client.put("/api/auth/me", json={"lang": "en"}).status_code == 200
    return client


def upload(client, data: bytes):
    return client.post(
        "/api/schema-map/preview",
        json={"filename": "sablon.xlsx", "content_b64": base64.b64encode(data).decode()},
    )


def apply(client, preview_id: str):
    return client.post("/api/schema-map/apply", json={"preview_id": preview_id})


def wait_done(client, preview_id: str, timeout: float = 180.0) -> dict:
    """İndeks işi bitmiş ya da düşmüştür; iş parçacığı testin dünyasında koştu için beklenir."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/api/schema-map/status/{preview_id}").json()
        if status["phase"] in ("done", "failed"):
            return status
        time.sleep(0.05)
    raise AssertionError(f"iş bitmedi: {preview_id}")


# ------------------------------------------------------------------ şablonu kodla doldurmak


def column_row(lang: str, row: tuple) -> tuple:
    """Kolon satırı: işaretler şablonun kendi listesindeki yazımla (E/H ya da Y/N) yazılır."""
    labels = template.LABELS[lang]
    cells = [TABLE, *row]
    for index in (6, 8):  # KAPALI / CLOSED ve NULL / NULL
        cells[index] = labels["yes"] if cells[index] else labels["no"]
    return tuple(cells)


def fill(content: bytes, lang: str, name: str, *, defect: bool = False) -> bytes:
    """İndirilen boş şablona o dilin başlıklarıyla aynı içeriği yazar (``defect``: boş TİP)."""
    labels = template.LABELS[lang]
    book = openpyxl.load_workbook(io.BytesIO(content))
    rows = {
        "dataset": [(name, *DATASET_TAIL)],
        "tables": [TABLE_ROW],
        "columns": [column_row(lang, row) for row in COLUMN_ROWS],
        "rules": [RULE_ROW],
    }
    for role, index in ROLES.items():
        for offset, row in enumerate(rows[role], start=2):
            for column, value in enumerate(row, start=1):
                if value not in (None, ""):
                    book[labels["sheets"][index]].cell(row=offset, column=column, value=value)
    if defect:
        sheet = book[labels["sheets"][ROLES["columns"]]]
        headers = [cell.value for cell in sheet[1]]
        sheet.cell(
            row=3, column=headers.index(labels["column_headers"][2]) + 1
        ).value = None
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def sheet_names(content: bytes) -> list[str]:
    book = openpyxl.load_workbook(io.BytesIO(content))
    try:
        return [name for name in book.sheetnames if name != template.INFO_SHEET]
    finally:
        book.close()


def turkish(text: str) -> bool:
    return any(character in TURKISH_LETTERS for character in text)


def applied(world, client, lang: str, name: str) -> dict:
    """Şablonun o dilin yöneticisi tarafından uygulanması: diskte doğan iki dosyanın baytları."""
    preview = upload(client, fill(client.get(TEMPLATE_URL).content, lang, name)).json()
    assert preview["errors"] == [] and preview["warnings"] == []
    response = apply(client, preview["preview_id"])
    assert response.status_code == 200, response.text
    assert wait_done(client, preview["preview_id"])["phase"] == "done"
    folder = world.root / "real_datasets" / name
    return {file: (folder / file).read_bytes() for file in ("schema.json", "rules.json")}


# ------------------------------------------------------------------ tercih ve cevabın dili


def test_an_admin_who_chooses_english_is_answered_in_english(world):
    admin = ingiliz_yonetici(world)

    assert admin.get("/api/auth/me").json()["lang"] == "en"
    answer = admin.post("/api/ask", json={"question": E01["question"], "mode": "full"})

    assert answer.status_code == 200
    payload = answer.json()
    assert payload["status"] == "answered", payload["error"]
    assert payload["answer_lang"] == "en"
    assert payload["sql"] == E01["sql"], "İngilizce soru İngilizce altın kaydı koşmadı"
    assert payload["row_count"] > 0, "boş cevap hiçbir şeyi doğrulamaz"
    assert payload["facts"][0]["label"].startswith(t("facts.row_count", "en"))
    assert not any(turkish(fact["label"]) for fact in payload["facts"])


def test_the_blank_question_is_refused_in_the_language_of_the_person(world):
    english, turkish_client = ingiliz_yonetici(world), girisli(world.app, USER)

    refused = english.post("/api/ask", json={"question": "   "})
    # ASSUMPTION: boş sorunun reddi yolun bugünkü 400'idür (brief "422" yazıyor; R8-5'in ölçtüğü
    # şey durum değil cümlenin dilidir - ``test_web_route_matrix`` de 400'ü sabitler).
    assert refused.status_code == 400
    assert refused.json() == {"detail": t("app.blank_question", "en")}

    same = turkish_client.post("/api/ask", json={"question": "   "})
    assert same.status_code == 400
    assert same.json() == {"detail": t("app.blank_question", "tr")}


# ------------------------------------------------------------------ şablonun İngilizce yolu


def test_the_english_template_downloads_previews_and_applies(world):
    admin = ingiliz_yonetici(world)

    download = admin.get(TEMPLATE_URL)
    assert download.status_code == 200
    assert download.headers["content-disposition"] == (
        f'attachment; filename="{config.TEMPLATE_FILENAMES["en"]}"'
    )
    assert sheet_names(download.content) == list(template.LABELS["en"]["sheets"])

    preview = upload(admin, fill(download.content, "en", EN_DATASET))

    assert preview.status_code == 200
    body = preview.json()
    assert body["errors"] == [] and body["warnings"] == []
    assert body["counts"] == {
        "tables": 1, "columns": 4, "pii": 0, "deny": 1, "references": 1, "rules": 1,
    }
    assert body["db_check"]["message"] == t("template.issue.no_db", "en")
    assert not turkish(body["db_check"]["message"])

    applied = apply(admin, body["preview_id"])
    assert applied.status_code == 200, applied.text
    assert wait_done(admin, body["preview_id"])["phase"] == "done"

    ds = datasets.load_dataset(EN_DATASET)
    assert ds.root == world.root / "real_datasets" / EN_DATASET
    assert [table["name"] for table in ds.schema()["tables"]] == [TABLE.upper()]
    assert [rule["id"] for rule in ds.rules()] == [RULE_ROW[0]]


def test_the_same_content_in_the_turkish_template_applies_to_the_same_bytes(world):
    english, turkish_admin = ingiliz_yonetici(world), girisli(world.app, ADMIN)

    assert applied(world, english, "en", f"{EN_DATASET}_karsilik") == applied(
        world, turkish_admin, "tr", f"{TR_DATASET}_karsilik"
    )


# ------------------------------------------------------------------ tercih yapmamış kişi


def test_a_turkish_user_sees_todays_turkish_texts(world):
    admin = girisli(world.app, ADMIN)

    download = admin.get(TEMPLATE_URL)
    assert download.headers["content-disposition"] == (
        f'attachment; filename="{config.TEMPLATE_FILENAMES["tr"]}"'
    )
    assert sheet_names(download.content) == list(template.LABELS["tr"]["sheets"])

    broken = upload(admin, fill(download.content, "tr", TR_DATASET, defect=True)).json()
    assert [issue["message"] for issue in broken["errors"]] == [
        t("template.issue.required_cell", "tr", header=template.LABELS["tr"]["column_headers"][2])
    ]
    assert broken["db_check"]["message"] == t("template.issue.no_db", "tr")

    # Adres dosyanın kendi başlığıdır (TİP), cümlenin dili ise isteğindir (en).
    header = template.LABELS["tr"]["column_headers"][2]
    foreign = upload(
        ingiliz_yonetici(world),
        fill(admin.get(f"{TEMPLATE_URL}?lang=tr").content, "tr", TR_DATASET, defect=True),
    ).json()
    assert [issue["message"] for issue in foreign["errors"]] == [
        t("template.issue.required_cell", "en", header=header)
    ]
    assert foreign["db_check"]["message"] == t("template.issue.no_db", "en")


# ------------------------------------------------------------------ komut satırı


def test_the_cli_eval_in_english_measures_the_english_golden_set(world, capsys):
    code = cli.main(["eval", "--lang", "en", "--llm", "fake", "--dataset", "wwi"])
    capsys.readouterr()

    assert code == 0
    report = datasets.load_dataset("wwi").eval_out / "full" / "latest" / "report.json"
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["lang"] == "en"
    assert data["score"] == {"passed": len(WWI.golden("en")), "total": len(WWI.golden("en"))}
    assert {question["outcome"] for question in data["questions"]} == {"pass"}
