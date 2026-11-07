# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""R8-13 (T418): kuralın İngilizce eş anlamlıları - doğrulama, API, indeks, genişletme.

İddia çeviri değil erişilebilirlik: İngilizce sorulan bir soru, Türkçe karşılığı kuralın
`synonyms_en` listesinde durduğu için aynı kuralı bulmalı. Kanıt gerçek yoldan verilir - tmp'ye
yazılan kurallar `cli.build_index`le (sahte embedder) indekslenir, `load_search`le geri okunur ve
İngilizce kelime orada kuralı bulur; anahtarı taşımayan aynı kurallar listesi bulamaz. Anahtarı
taşımayan bir kuralın dokümanı ve disk kaydı ise bugünkü hâlinin ta kendisidir: alan boşken diske
hiç yazılmaz, okuyan taraf yoksa [] sayar.

ASSUMPTION: alan artık sözleşmede olduğu için şablonun `EŞ ANLAMLILAR (EN)` hücresi de kurala
girer; örnek şablonun kuralını `synonyms_en`siz sayan test_template_read.py ve
test_onboard_apply.py sabitleri bu görevle bayatlar (o hücre test_template_en.py'de sabit).
"""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bilgin import config
from bilgin.app.session import open_session
from bilgin.cli import main as cli
from bilgin.index.docs import build_documents
from bilgin.index.search import load_search, synonym_query
from bilgin.index.text import fold
from bilgin.schema_map.doc import load_schema
from bilgin.schema_map.rules import load_rules, rule_text, rules_text
from bilgin.schema_map.rules_edit import normalize_rule, validate_rule
from bilgin.web.app import create_app

SCHEMA = load_schema()
RULES = load_rules()
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
# `ciro` kuralının İngilizce karşılığı: şemanın hiçbir dokümanında geçmeyen bir kelime, yani
# bulunursa tek yolu synonyms_en'dir.
ENGLISH = "revenue"
ENGLISH_RULES = {
    "id": "ciro",
    "term": "Ciro (net satış hasılatı)",
    "synonyms": ["ciro", "net ciro", "satış hasılatı", "satış geliri", "ciro tutarı"],
    "definition": "Satış hareketlerinin KDV hariç toplamı.",
    "sql_hint": "SUM(s.STHAR_GCMIK * s.STHAR_NF)",
    "tables": ["TBLSTHAR"],
    "markers": ["STHAR_GCMIK"],
    "synonyms_en": ["revenue", "net revenue"],
}


def _rule(**over):
    """Doğrulama ve normalize için temiz kural (gerçek sentetik şemanın tablosuyla)."""
    rule = {
        "id": "ingilizce_kural",
        "term": "Ciro (İngilizce)",
        "synonyms": ["ciro"],
        "definition": "Satış hareketlerinin toplamı.",
        "sql_hint": "SUM(STHAR_GCMIK)",
        "tables": ["TBLSTHAR"],
        "markers": ["STHAR_GCMIK"],
    }
    rule.update(over)
    return rule


def _mini_rule(**over):
    """Kural API'sinin kümesi mini şemayı konuşuyor (R5-16'nın test dünyasıyla aynı kural)."""
    rule = {
        "id": "brut_ciro",
        "term": "Brüt ciro",
        "synonyms": ["brüt"],
        "definition": "KDV dahil toplam.",
        "sql_hint": "SUM(l.LineAmount)",
        "tables": ["Sales.OrderLines"],
        "markers": [r"SUM\s*\(\s*(?:\w+\.)?LineAmount"],
    }
    rule.update(over)
    return rule


def _text_without_the_key(rule: dict) -> str:
    """Anahtar gelmeden önceki kural metni: dokümanın bugünkü hâliyle karşılaştırma ölçütü."""
    lines = [rule["term"]]
    if rule.get("synonyms"):
        lines.append("  Eş anlamlıları: " + ", ".join(rule["synonyms"]))
    if rule.get("definition"):
        lines.append("  Tanım: " + rule["definition"])
    if rule.get("sql_hint"):
        lines.append("  SQL ipucu: " + rule["sql_hint"])
    if rule.get("tables"):
        lines.append("  Tablolar: " + ", ".join(rule["tables"]))
    return "\n".join(lines)


@pytest.fixture
def english_rules(tmp_path):
    """`ciro`ya İngilizce listesi eklenmiş commit'lenmiş kurallar; tmp'de ayrı bir dosya."""
    rules = [
        dict(rule, synonyms_en=ENGLISH_RULES["synonyms_en"]) if rule["id"] == "ciro" else rule
        for rule in RULES
    ]
    path = tmp_path / "rules_en.json"
    path.write_text(json.dumps({"rules": rules}, ensure_ascii=False, indent=2), encoding="utf-8")
    return path, load_rules(path)


@pytest.fixture
def api(tmp_path, monkeypatch, capsys):
    """Mini kümesinin tmp kopyası üstünde gerçek oturum ve gerçek kapı (R5-16 dünyası)."""
    root = tmp_path / "datasets"
    shutil.copytree(FIXTURE_ROOT / "mini", root / "mini")
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(root))
    cli.build_database(dataset="mini")
    assert cli.build_index("fake", dataset="mini") == 0
    session = open_session(
        dataset="mini",
        llm="fake",
        audit_path=tmp_path / "audit.jsonl",
        ask_log=tmp_path / "asks.jsonl",
    )
    capsys.readouterr()
    client = TestClient(
        create_app(session, saved_path=tmp_path / "bilgin.db", static_dir=tmp_path / "static")
    )
    return session, client


def ids(hits) -> list[str]:
    return [hit.doc_id for hit in hits]


# ------------------------------------------------------------------ doğrulama


def test_a_clean_english_list_passes():
    assert validate_rule(_rule(synonyms_en=["revenue", "net revenue"]), SCHEMA, []) == []


def test_the_key_is_optional():
    assert validate_rule(_rule(), SCHEMA, []) == []


@pytest.mark.parametrize("value", ["revenue", ["revenue", 7], {"en": "revenue"}])
def test_an_english_list_that_is_not_texts_reports_its_own_field(value):
    errors = validate_rule(_rule(synonyms_en=value), SCHEMA, [])
    hit = [error for error in errors if error["field"] == "synonyms_en"]
    assert hit, f"synonyms_en için hata yok: {errors}"
    assert "Eş anlamlılar (İngilizce)" in hit[0]["message"]


def test_normalize_keeps_the_english_list_clean():
    rule = normalize_rule(_rule(synonyms_en=[" revenue ", "", "  ", "net revenue"]))
    assert rule["synonyms_en"] == ["revenue", "net revenue"]


def test_normalize_leaves_a_rule_without_the_key_untouched():
    assert normalize_rule(_rule()) == {
        "id": "ingilizce_kural",
        "term": "Ciro (İngilizce)",
        "synonyms": ["ciro"],
        "definition": "Satış hareketlerinin toplamı.",
        "sql_hint": "SUM(STHAR_GCMIK)",
        "tables": ["TBLSTHAR"],
        "markers": ["STHAR_GCMIK"],
    }


# ------------------------------------------------------------------ prompt ve doküman metni


def test_the_full_rules_prompt_lists_both_languages():
    block = rules_text([dict(ENGLISH_RULES)])
    assert "  Eş anlamlıları: " + ", ".join(ENGLISH_RULES["synonyms"]) in block
    assert "  Eş anlamlıları (İngilizce): revenue, net revenue" in block


def test_a_rule_without_the_key_reads_as_it_always_did():
    assert rule_text(_rule()) == _text_without_the_key(_rule())


def test_the_rule_document_text_carries_both_lists():
    texts = {doc.id: doc.text for doc in build_documents(SCHEMA, [dict(ENGLISH_RULES)])}
    assert "  Eş anlamlıları (İngilizce): revenue, net revenue" in texts["rule:ciro"]


@pytest.mark.parametrize("rule", RULES, ids=lambda rule: rule["id"])
def test_a_rule_without_the_key_indexes_exactly_as_today(rule):
    if rule.get("synonyms_en"):
        pytest.skip("bu kural iki dili de taşıyor; bugünkü metin ölçütü anahtarsız olan")
    texts = {doc.id: doc.text for doc in build_documents(SCHEMA, [rule])}
    assert texts[f"rule:{rule['id']}"] == _text_without_the_key(rule)


# ------------------------------------------------------------------ eş anlamlı genişletmesi


def test_the_rewrite_hears_the_english_word():
    asked = fold(synonym_query("What was the total revenue?", [dict(ENGLISH_RULES)]))
    assert asked.startswith(fold("What was the total revenue?"))
    for synonym in ENGLISH_RULES["synonyms"]:
        assert fold(synonym) in asked


def test_the_rewrite_adds_nothing_to_an_english_word_it_does_not_know():
    assert synonym_query("What was the total revenue?", RULES) == "What was the total revenue?"


# ------------------------------------------------------------------ tmp indekste gerçek arama


def test_an_english_word_only_in_synonyms_en_finds_the_rule(tmp_path, english_rules, capsys):
    path, rules = english_rules
    index = tmp_path / "index"
    assert cli.build_index("fake", index_dir=index, rules_path=path) == 0
    capsys.readouterr()

    hits = load_search(index, SCHEMA, rules).search(
        "How much was the total revenue last month?", collection="rules"
    )
    assert ids(hits)[0] == "rule:ciro"


def test_the_same_word_finds_nothing_when_no_rule_carries_it(tmp_path, capsys):
    index = tmp_path / "index"
    assert cli.build_index("fake", index_dir=index, rules_path=config.RULES_PATH) == 0
    capsys.readouterr()

    hits = load_search(index, SCHEMA, RULES).search(
        "How much was the total revenue last month?", collection="rules"
    )
    assert "rule:ciro" not in ids(hits)


# ------------------------------------------------------------------ kural API'si


def test_the_api_round_trips_the_english_synonyms(api):
    session, client = api
    body = _mini_rule(synonyms_en=["revenue", "net revenue"])

    added = client.post("/api/rules", json=body).json()
    on_disk = json.loads(session.dataset.rules_path.read_text(encoding="utf-8"))["rules"]

    assert [rule for rule in added["rules"] if rule["id"] == "brut_ciro"][0]["synonyms_en"] == [
        "revenue",
        "net revenue",
    ]
    assert [rule for rule in on_disk if rule["id"] == "brut_ciro"][0]["synonyms_en"] == [
        "revenue",
        "net revenue",
    ]

    edited = client.put("/api/rules/brut_ciro", json={**body, "synonyms_en": ["turnover"]}).json()
    assert [rule for rule in edited["rules"] if rule["id"] == "brut_ciro"][0]["synonyms_en"] == [
        "turnover"
    ]
    assert client.get("/api/rules").json()["rules"] == edited["rules"]


def test_a_rule_posted_without_the_key_is_stored_without_it(api):
    session, client = api
    client.post("/api/rules", json=_mini_rule(id="duz_kural"))
    on_disk = json.loads(session.dataset.rules_path.read_text(encoding="utf-8"))["rules"]
    assert "synonyms_en" not in [rule for rule in on_disk if rule["id"] == "duz_kural"][0]


def test_an_english_list_that_is_not_texts_is_422(api):
    session, client = api
    before = session.dataset.rules_path.read_text(encoding="utf-8")

    response = client.post("/api/rules", json=_mini_rule(synonyms_en="revenue"))

    assert response.status_code == 422
    assert "synonyms_en" in {error["field"] for error in response.json()["errors"]}
    assert session.dataset.rules_path.read_text(encoding="utf-8") == before
