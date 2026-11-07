# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T355: konuşmayı açan yol da kümeyi süzer (PLAN R7-2, R7-8).

Dünya ``tests/test_web_conversations_api.py`` ile aynı - kurulmuş mini küme, sahte model, tmp
dosyalar - ama burada süzgecin ekseni sahiplik değil küme: ``ask`` ve liste oturumun kümesinin
dışındakini hiç görmezken tek konuşmayı açan yol ona bakmıyordu, yani yönetici kümeyi
değiştirdikten sonra eski ``#/c/<id>`` öteki kümenin SQLini ve satırlarını göstermeye devam
ediyordu. Konuşma deposu uygulamanın kendi deposudur (``app.state.conversations``), o yüzden
"öteki kümenin konuşması" oraya yazılmış gerçek bir satırdır; sahipliğin 404'ü ile aynı cümle.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bilgin import config
from bilgin.app.session import open_session
from bilgin.cli import main as cli
from bilgin.web.app import create_app

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
# Sözleşme cümlesi: olmayanla başkasınınki ve başkasının kümesindeki aynı şeyi söyler.
NOT_FOUND = {"detail": "Konuşma bulunamadı."}


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(FIXTURE_ROOT))
    cli.build_database(dataset="mini")
    return tmp_path


@pytest.fixture
def app(project, capsys):
    """Kümesi ``mini`` olan sunucu: oturumun kümesinin dışı ``other``tır.

    Tek kullanıcılı kurulum: sahiplik süzgeci devre dışı, yani görülen 404 yalnız kümenin süzdüğüdür.
    """
    capsys.readouterr()
    session = open_session(
        dataset="mini",
        llm="fake",
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
    )
    return create_app(session, saved_path=project / "bilgin.db", static_dir=project / "static")


def question(app, qid):
    return next(item for item in app.state.session.dataset.golden() if item["id"] == qid)["question"]


def ask(app, text):
    response = TestClient(app).post("/api/ask", json={"question": text, "conversation_id": None})
    assert response.status_code == 200, response.text
    return response.json()["conversation_id"]


def foreign_conversation(app, dataset="other"):
    """Aynı depoda, başka bir kümenin adına yazılmış konuşma: bir turu da vardır."""
    store = app.state.conversations
    cid = store.create(dataset=dataset, title="Öteki kümenin konuşması")
    store.add_turn(cid, {"question": "Öteki kümenin sorusu", "status": "answered", "sql": "SELECT 1"})
    return cid


def test_a_conversation_of_another_dataset_is_not_there(app):
    client = TestClient(app)
    own = ask(app, question(app, "Q01"))
    other = foreign_conversation(app)

    assert client.get(f"/api/conversations/{other}").json() == NOT_FOUND
    assert client.get(f"/api/conversations/{own}").status_code == 200, "kendi kümesi yerinde"
    assert [item["id"] for item in client.get("/api/conversations").json()["conversations"]] == [own]


def test_delete_stays_by_owner_only(app):
    """Silmenin süzgeci küme değil (R7-8): öteki kümenin konuşması da kendi deposundan silinir."""
    client = TestClient(app)
    other = foreign_conversation(app)

    assert client.delete(f"/api/conversations/{other}").json() == {"deleted": True}
