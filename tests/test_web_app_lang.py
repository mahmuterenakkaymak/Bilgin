# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T404: app.py'nin red cümleleri, yedek sayfası ve Excel sayfasının adı isteğin dilinde (PLAN R8-5).

Dünya test_web_api'ninki: kurulmuş mini küme, sahte model, tmp günlükler. Dil tek bir başlıkla
seçilir - ``Accept-Language`` - yani aynı dünyanın kapısı iki dilde de okunur. tr tarafı bugün
ekranda okunan cümleye sabittir: katalog bir gün bozulursa buradan anlaşılır.
"""

import csv
import io
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from bilgin import config
from bilgin.app import asklog
from bilgin.app.session import open_session
from bilgin.cli import main as cli
from bilgin.i18n import t
from bilgin.i18n.scan import user_literals
from bilgin.report import export as export_module
from bilgin.web import app as app_module
from bilgin.web.app import create_app

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
BOM = chr(0xFEFF)

# 2026-10-27'de ekranda okunan cümleler: Türkçe yolun kataloğa taşınırken değişmediğinin ölçütü.
TODAY = {
    "app.blank_question": "Soru boş.",
    "app.no_saved": "Kayıtlı soru bulunamadı.",
    "app.no_ask": "Bu sorunun kaydı bulunamadı.",
    "app.not_answered": "Yalnızca cevaplanmış bir soru dışa aktarılabilir.",
    "app.other_dataset": "Bu kayıt başka bir veri kümesine ait.",
    "app.no_rule": "Kural bulunamadı: {id}.",
    "app.duplicate_rule": "Bu kimlikte bir kural zaten var: {id}.",
    "app.rebuild_failed": "İndeks yeniden kurulamadı: embedding uç noktası yanıt vermiyor olabilir.",
    "app.no_ui": "Arayüz derlenmemiş",
    "rules.term_empty": "Terim boş olamaz.",
    "export.sheet": "Sonuç",
}

REJECTIONS = (
    "blank_ask",
    "blank_saved",
    "replay_unknown",
    "export_unknown",
    "export_not_answered",
    "export_other_dataset",
    "saved_unknown",
    "rule_unknown",
    "rule_duplicate",
)


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(FIXTURE_ROOT))
    cli.build_database(dataset="mini")
    return tmp_path


@pytest.fixture
def session(project, capsys):
    capsys.readouterr()
    return open_session(
        dataset="mini",
        llm="fake",
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
    )


@pytest.fixture
def client(session, project):
    app = create_app(session, saved_path=project / "bilgin.db", static_dir=project / "static")
    return TestClient(app)


@pytest.fixture
def logged(client, project):
    """Reddeden iki kaydın dünyası: 409'lar soru günlüğünün bu satırlarını okur."""
    asklog.record_ask(
        {"audit_id": "cevapsizkay1", "status": "failed", "sql": "SELECT 1"}, project / "asks.jsonl"
    )
    asklog.record_ask(
        {"audit_id": "baskabirkay1", "status": "answered", "sql": "SELECT 1", "dataset": "wwi"},
        project / "asks.jsonl",
    )
    return client


def set_lang(client, lang: str) -> None:
    """TestClient'ın varsayılan başlığı: sonraki her istek aynı dili ister."""
    client.headers["accept-language"] = lang


def expected(key: str, lang: str, **params) -> str:
    """Türkçe bugün okunan cümle, İngilizce kataloğun kendi satırı (R8-5)."""
    return TODAY[key].format(**params) if lang == "tr" else t(key, lang, **params)


def rejection(key: str, lang: str, **params) -> dict:
    """Red gövdesi: kural formunun alan hatası ``detail``in altında bir liste, ötekiler düz cümle."""
    text = expected(key, lang, **params)
    return {"detail": [{"field": "id", "message": text}] if key == "app.duplicate_rule" else text}


def reject(name: str, client, session):
    """Adı geçen redi koşar: (kataloğun anahtarı, parametreleri, gelen cevap)."""
    if name == "blank_ask":
        return "app.blank_question", {}, client.post("/api/ask", json={"question": "   "})
    if name == "blank_saved":
        return "app.blank_question", {}, client.post("/api/saved", json={"question": ""})
    if name == "replay_unknown":
        return "app.no_ask", {}, client.post("/api/replay/yokboylebir1")
    if name == "export_unknown":
        return "app.no_ask", {}, client.get("/api/export/yokboylebir1.csv")
    if name == "export_not_answered":
        return "app.not_answered", {}, client.get("/api/export/cevapsizkay1.xlsx")
    if name == "export_other_dataset":
        return "app.other_dataset", {}, client.get("/api/export/baskabirkay1.csv")
    if name == "saved_unknown":
        return "app.no_saved", {}, client.delete("/api/saved/42")
    if name == "rule_unknown":
        return "app.no_rule", {"id": "yok_kural"}, client.delete("/api/rules/yok_kural")
    rid = session.rules[0]["id"]
    body = {"id": rid, "term": "Çakışan terim", "definition": "Var olan kuralın üstüne."}
    return "app.duplicate_rule", {"id": rid}, client.post("/api/rules", json=body)


@pytest.mark.parametrize("lang", ["tr", "en"])
@pytest.mark.parametrize("name", REJECTIONS)
def test_a_rejection_reads_the_request_language(name, lang, logged, session):
    set_lang(logged, lang)
    key, params, response = reject(name, logged, session)

    assert response.status_code in (400, 404, 409)
    assert response.json() == rejection(key, lang, **params)


@pytest.mark.parametrize("lang", ["tr", "en"])
def test_rule_validation_errors_read_the_request_language(lang, client):
    set_lang(client, lang)
    response = client.post(
        "/api/rules", json={"id": "dil_kurali", "term": "   ", "definition": "Dolu bir tanım."}
    )

    assert response.status_code == 422
    assert response.json() == {"errors": [{"field": "term", "message": expected("rules.term_empty", lang)}]}


@pytest.mark.parametrize("lang", ["tr", "en"])
def test_a_failed_rebuild_speaks_the_request_language(lang, client, monkeypatch):
    monkeypatch.setattr(cli, "build_index", lambda *args, **kwargs: 1)
    set_lang(client, lang)

    response = client.post("/api/index/rebuild")

    assert response.status_code == 500
    assert response.json() == {"detail": expected("app.rebuild_failed", lang)}


@pytest.mark.parametrize("lang", ["tr", "en"])
def test_the_page_replacing_the_ui_speaks_the_request_language(lang, client):
    set_lang(client, lang)

    page = client.get("/")

    assert page.status_code == 200
    assert f'<html lang="{lang}">' in page.text
    assert t("app.no_ui", lang) in page.text
    assert t("app.no_ui.intro", lang) in page.text
    assert "npm --prefix web run build" in page.text
    if lang == "en":
        assert TODAY["app.no_ui"] not in page.text, "İngilizce sayfa Türkçe başlık taşıyamaz"


@pytest.mark.parametrize("lang", ["tr", "en"])
def test_the_xlsx_sheet_is_named_in_the_request_language(lang, client, session):
    set_lang(client, lang)
    line = next(item for item in session.dataset.golden() if item["id"] == "Q01")
    body = client.post("/api/ask", json={"question": line["question"]}).json()
    assert body["status"] == "answered"

    xlsx = client.get(f"/api/export/{body['audit_id']}.xlsx")
    csv_file = client.get(f"/api/export/{body['audit_id']}.csv")

    assert xlsx.status_code == 200
    sheet = openpyxl.load_workbook(io.BytesIO(xlsx.content)).active
    assert sheet.title == expected("export.sheet", lang)
    text = csv_file.content.decode("utf-8")
    rows = list(csv.reader(io.StringIO(text[len(BOM) :]), delimiter=";"))
    assert rows[0] == body["columns"], "kolon satırı SQL'in adlarıdır, çevrilmez"


def test_no_turkish_literal_is_left_in_the_two_modules():
    assert user_literals(Path(app_module.__file__)) == []
    assert user_literals(Path(export_module.__file__)) == []
