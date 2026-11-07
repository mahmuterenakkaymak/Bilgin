# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T174: M14 entegrasyonu — iki gerçek dünya, uçtan uca, elle yapılmış tek parça olmadan.

Dünya gerçek ``load_dataset``ın kendi builder'ı, kapı gerçek ``open_session``ın gerçek yürütücüsü,
ekran gerçek ``create_app``ın ``TestClient``ı: elle kurulmuş tek bir ``Session``/``Result``/doğru
yok. Fazın iddiası beş cümle: iki dünyanın her altın sorusu ``/api/ask``ta cevaplanır ve satırları
(PII maskesi uygulanmış) Python doğrulusuyla 2 haneye indirilmiş haliyle farksız; ``ask --json``ın
payload'ı aynı sorunun API payload'ıyla ``audit_id`` ve gecikmeler dışında birebir aynıdır;
uyarılar Contracts'ın sözlükleridir; her cevaplanmış sorunun dışa aktarımı yürütücünün yeniden
koşumudur ve payload satırlarına eşittir; bir PII seçimi payload'da, CSV'de ve XLSX'te maskeli
kalır; geçmiş her soruyu listeler.
"""

import io
import json

import openpyxl
import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from bilgin import config, datasets
from bilgin.agent import fake
from bilgin.app.session import open_session
from bilgin.cli import main as cli
from bilgin.engine.result import Result
from bilgin.eval import compare
from bilgin.policy import pii
from bilgin.report.export import to_csv_bytes
from bilgin.web.app import create_app

DATASETS = ("synthetic_erp", "wwi")
MODE = "full"  # altın kayıt indekssiz oynanır; iki dünya için de cevap yolu aynı

# PII seçimi: kümenin kendi şemasında ``pii`` işaretli bir kolonu seçen sabit bir SQL.
PII_SQL = {
    "synthetic_erp": "SELECT PERSONEL_KODU, TCKN FROM TBLPERSONEL ORDER BY PERSONEL_KODU",
    "wwi": "SELECT PersonID, FullName FROM Application.People ORDER BY PersonID",
}
PII_COLUMN = {"synthetic_erp": "TCKN", "wwi": "FullName"}
# Ham değerler doğruluğu üreten bellek satırlarından okunur (SQLite tablo adına bağlanmadan).
PII_SOURCE = {"synthetic_erp": ("TBLPERSONEL", "TCKN"), "wwi": ("Application.People", "FullName")}

# Contracts "warning": uyarının taşıdığı anahtarlar; kolon yalnız kolon başına denetimlerde dolu.
WARNING_KEYS = {"code", "message", "column"}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """İki dünyanın tmp'de kurulmuş dosyaları, gerçek oturumları ve üstlerindeki TestClient'lar.

    ``config.ROOT`` tmp'ye çevrilir ki hem ``open_session`` hem ``ask --json`` (yolları config'den
    okur) aynı tmp veritabanını görsün; ``AUDIT_LOG``/``ASK_LOG`` da tmp'ye alınır, böylece CLI
    koşumu deposunun gerçek günlüklerine dokunmaz.
    """
    folder = tmp_path_factory.mktemp("m14")
    mp = MonkeyPatch()
    mp.setattr(config, "ROOT", folder)
    mp.setattr(config, "AUDIT_LOG", folder / "cli-audit.jsonl")
    mp.setattr(config, "ASK_LOG", folder / "cli-asks.jsonl")
    built = {}
    for name in DATASETS:
        ds = datasets.load_dataset(name)
        ds.db_path.parent.mkdir(parents=True, exist_ok=True)
        ds.build_db(db_path=ds.db_path, sql_path=folder / f"{name}.sql")
        session = open_session(
            dataset=name,
            llm="fake",
            audit_path=folder / f"{name}-audit.jsonl",
            ask_log=folder / f"{name}-asks.jsonl",
        )
        client = TestClient(
            create_app(session, saved_path=folder / f"bilgin-{name}.db", static_dir=folder / "static")
        )
        built[name] = (ds, session, client)
    yield folder, built
    mp.undo()


def ask(client, question):
    body = client.post("/api/ask", json={"question": question, "mode": MODE}).json()
    assert body["status"] == "answered", body.get("error")
    return body


def truth(rows, columns):
    """Python doğrulusu, kıyaslayıcının gördüğü biçimde: kolon adları sayı, değerler gerçek."""
    return Result(
        columns=[str(i) for i in range(len(columns))],
        rows=[tuple(row) for row in rows],
        row_count=len(rows),
    )


def assert_rows_equal_reference(payload, ref_rows, ordered, schema):
    """Payload satırları Python doğrulusuna eşit (2 haneye indirilmiş, sıra yalnız ``ordered``da).

    ASSUMPTION: yürütücü PII kolonlarını maskelediği için payload'daki maske, doğrulunun aynı
    kolonlarına kümenin şemasındaki sınıfla uygulanır; böylece satırlar tüm kolonlarla karşılaştırılır
    (R3-6: maske her yerde, doğruluk ham).
    """
    columns = payload["columns"]
    masked = set(payload["masked_columns"])
    by_column = {}
    for (_table, column), cls in pii.column_map(schema).items():
        by_column.setdefault(column, cls)
    masked_rows = [
        tuple(
            pii.mask(by_column[name.upper()], value)
            if name in masked and name.upper() in by_column
            else value
            for name, value in zip(columns, ref)
        )
        for ref in ref_rows
    ]
    verdict = compare.compare(
        truth(masked_rows, columns),
        Result(columns=columns, rows=[tuple(r) for r in payload["rows"]], row_count=len(payload["rows"])),
        ordered,
    )
    assert verdict.match, f"{verdict.reason}"
    assert verdict.extra_columns == []


def assert_warnings_are_contract_dicts(warnings):
    assert isinstance(warnings, list)
    for warning in warnings:
        assert set(warning) == WARNING_KEYS
        assert isinstance(warning["code"], str) and isinstance(warning["message"], str)
        assert warning["column"] is None or isinstance(warning["column"], str)


def raw_pii_values(ds, name):
    table, column = PII_SOURCE[name]
    return [row[column] for row in ds.generate()[table] if row.get(column)]


def xlsx_grid(content):
    sheet = openpyxl.load_workbook(io.BytesIO(content)).active
    return [[cell.value for cell in row] for row in sheet.iter_rows()]


# ------------------------------------------------- her altın soru cevaplanır ve doğrulusuna eşit


@pytest.mark.parametrize("name", DATASETS)
def test_every_golden_question_is_answered_and_equals_its_reference(name, world):
    ds, _, client = world[1][name]
    rows = ds.generate()
    refs = ds.references()
    for line in ds.golden():
        body = ask(client, line["question"])
        assert body["rows"], f"{line['id']} boş döndü; soru hiçbir şey ölçmüyor"
        assert body["sql"] == line["sql"], f"{line['id']} gönderilen SQL altın SQL değil"
        assert_rows_equal_reference(body, refs[line["id"]](rows), line["ordered"], ds.schema())
        assert_warnings_are_contract_dicts(body["warnings"])


# ------------------------------------------------- ask --json payload'ı API payload'ıdır


@pytest.mark.parametrize("name", DATASETS)
def test_ask_json_payload_equals_the_api_payload(name, world, capsys):
    ds, _, client = world[1][name]
    line = ds.golden()[1]  # Q02: satır taşıyan bir soru
    api = ask(client, line["question"])

    code = cli.main(
        ["ask", line["question"], "--llm", "fake", "--dataset", name, "--mode", MODE, "--json"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["status"] == "answered"
    # Updated 2026-10-26 with Eren's approval: Run 7 (PLAN R7-8) adds conversation_id, turn and context to every API payload.
    # The API always runs a conversation turn; a CLI ask without --conversation does not, so those three keys
    # (like audit_id, per-call values) are compared apart: present on the API, never on the plain CLI ask.
    conv = ("conversation_id", "turn", "context")
    assert all(k in api for k in conv) and not any(k in payload for k in conv)
    strip = lambda p: {k: v for k, v in p.items() if k not in ("audit_id", "timings", *conv)}
    assert strip(payload) == strip(api)


# ------------------------------------------------- dışa aktarım payload satırlarının yeniden koşumu


@pytest.mark.parametrize("name", DATASETS)
def test_export_of_each_answered_ask_equals_its_payload_rows(name, world):
    ds, _, client = world[1][name]
    for line in ds.golden():
        body = ask(client, line["question"])
        audit_id = body["audit_id"]

        csv_response = client.get(f"/api/export/{audit_id}.csv")
        xlsx_response = client.get(f"/api/export/{audit_id}.xlsx")

        assert csv_response.status_code == 200 and xlsx_response.status_code == 200
        # CSV: yürütücünün yeniden koşumu payload satırlarının birebir kanonik dosyasıdır.
        assert csv_response.content == to_csv_bytes(body["columns"], body["rows"])
        # XLSX: başlık + satırlar sayı olarak durur; XLSX ondalığı ~15 anlamlı hanede tuttuğu için
        # satırlar projenin sayı ölçütüyle (2 haneye indirilmiş, sıralı) kıyaslanır.
        grid = xlsx_grid(xlsx_response.content)
        assert grid[0] == body["columns"]
        verdict = compare.compare(
            Result(columns=body["columns"], rows=[tuple(r) for r in body["rows"]], row_count=len(body["rows"])),
            Result(columns=grid[0], rows=[tuple(r) for r in grid[1:]], row_count=len(grid) - 1),
            ordered=True,
        )
        assert verdict.match, f"{line['id']}: {verdict.reason}"


# ------------------------------------------------- bir PII seçimi üç yüzeyde de maskeli kalır


@pytest.mark.parametrize("name", DATASETS)
def test_a_pii_select_stays_masked_in_payload_csv_and_xlsx(name, world):
    folder = world[0]
    ds = datasets.load_dataset(name)
    session = open_session(
        dataset=name,
        llm="fake",
        audit_path=folder / f"pii-{name}-audit.jsonl",
        ask_log=folder / f"pii-{name}-asks.jsonl",
        client_factory=lambda mode: fake.FakeLLM(fake.wrong_sql(PII_SQL[name])),
    )
    client = TestClient(
        create_app(session, saved_path=folder / f"pii-{name}.db", static_dir=folder / "static")
    )
    raw = raw_pii_values(ds, name)
    assert raw, "küme maskelenecek ham PII değeri taşımalı"

    body = ask(client, "Kişisel veriler neler?")
    column = PII_COLUMN[name]
    index = body["columns"].index(column)
    assert column in body["masked_columns"]
    assert all(row[index] for row in body["rows"]), "maskeli kolon dolu olmalı"
    assert all(row[index] not in raw for row in body["rows"])
    flat = json.dumps(body["rows"], ensure_ascii=False)
    for value in raw:
        assert value not in flat, "ham PII payload'a sızmamalı"

    audit_id = body["audit_id"]
    csv_text = client.get(f"/api/export/{audit_id}.csv").content.decode("utf-8")
    cells = [cell for row in xlsx_grid(client.get(f"/api/export/{audit_id}.xlsx").content) for cell in row]
    for value in raw:
        assert value not in csv_text, "ham PII CSV'ye sızmamalı"
        assert value not in cells, "ham PII XLSX'e sızmamalı"


# ------------------------------------------------- geçmiş her soruyu listeler


def test_history_lists_every_ask(world):
    folder = world[0]
    ds = datasets.load_dataset("synthetic_erp")
    session = open_session(
        dataset="synthetic_erp",
        llm="fake",
        audit_path=folder / "hist-audit.jsonl",
        ask_log=folder / "hist-asks.jsonl",
    )
    client = TestClient(
        create_app(session, saved_path=folder / "hist.db", static_dir=folder / "static")
    )
    audit_ids = [ask(client, line["question"])["audit_id"] for line in ds.golden()[:3]]

    history = client.get("/api/history").json()["history"]

    assert [item["audit_id"] for item in history] == list(reversed(audit_ids))
    assert all(item["status"] == "answered" and item["sql"] for item in history)
    assert all("rows" not in item for item in history), "geçmiş veri satırı taşımaz"
