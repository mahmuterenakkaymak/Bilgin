"""T167: soru günlüğü (PLAN R5-4, Contracts "ask record" / "history item").

Kayıt sözleşme alanları dışında hiçbir şey taşımaz - özellikle satır yok. Geçmiş en yeni önce
gelir ve ``source`` alanını taşımaz; boş satırlar, bozuk satırlar ve olmayan dosya sessizce
geçilir.
"""

import json
import re

from nl2sql.app import asklog

CONTRACT_KEYS = {
    "ts",
    "audit_id",
    "source",
    "dataset",
    "mode",
    "question",
    "choice",
    "status",
    "sql",
    "row_count",
    "error",
}


def _entry(**overrides):
    entry = {
        "audit_id": asklog.new_audit_id(),
        "source": "web",
        "dataset": "mini",
        "mode": "full",
        "question": "Geçen ayın net cirosu ne kadar?",
        "status": "answered",
        "sql": "SELECT SUM(MIKTAR) FROM TBLSTHAR",
        "row_count": 1,
    }
    entry.update(overrides)
    return entry


def _log(tmp_path, name="asks.jsonl"):
    return tmp_path / "logs" / name


# ------------------------------------------------------------------ audit_id


def test_new_audit_id_is_12_hex_and_unique():
    ids = [asklog.new_audit_id() for _ in range(200)]
    assert all(re.fullmatch(r"[0-9a-f]{12}", value) for value in ids)
    assert len(set(ids)) == len(ids)


# ------------------------------------------------------------------ record_ask: sözleşme satırı


def test_record_ask_writes_only_the_contract_keys(tmp_path):
    path = _log(tmp_path)
    entry = _entry(rows=[[1234.56]], columns=["NET"], notes=["not"], model="fake")
    asklog.record_ask(entry, path)

    text = path.read_text(encoding="utf-8")
    assert text.count("\n") == 1
    assert "rows" not in text and "1234.56" not in text
    record = json.loads(text)
    assert set(record) == CONTRACT_KEYS
    assert record["audit_id"] == entry["audit_id"]
    assert record["question"] == entry["question"]
    assert record["ts"]  # AskPayload'da ts yok; günlüğü yazan üretiyor
    assert path.parent.name == "logs"


def test_record_ask_keeps_turkish_readable(tmp_path):
    path = _log(tmp_path)
    asklog.record_ask(_entry(question="ŞOK Marketin KDV hariç cirosu?"), path)
    assert "ŞOK Marketin KDV hariç cirosu?" in path.read_text(encoding="utf-8")


def test_record_ask_missing_optional_keys_get_defaults(tmp_path):
    path = _log(tmp_path)
    entry = _entry()
    for key in ("choice", "sql", "row_count", "error"):
        entry.pop(key, None)
    asklog.record_ask(entry, path)
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["choice"] is None
    assert record["sql"] == ""
    assert record["row_count"] == 0
    assert record["error"] is None


def test_record_ask_appends_in_order(tmp_path):
    path = _log(tmp_path)
    for index in range(3):
        asklog.record_ask(_entry(question=f"soru {index}"), path)
    assert [json.loads(line)["question"] for line in path.read_text(encoding="utf-8").splitlines()] == [
        "soru 0",
        "soru 1",
        "soru 2",
    ]


# ------------------------------------------------------------------ history


def test_history_is_newest_first_without_source(tmp_path):
    path = _log(tmp_path)
    ids = [asklog.new_audit_id() for _ in range(5)]
    for audit_id in ids:
        asklog.record_ask(_entry(audit_id=audit_id), path)
    items = asklog.history(path, n=5)
    assert [item["audit_id"] for item in items] == list(reversed(ids))
    assert all("source" not in item for item in items)
    assert set(items[0]) == CONTRACT_KEYS - {"source"}


def test_history_respects_n(tmp_path):
    path = _log(tmp_path)
    for index in range(7):
        asklog.record_ask(_entry(question=f"soru {index}"), path)
    items = asklog.history(path, n=3)
    assert [item["question"] for item in items] == ["soru 6", "soru 5", "soru 4"]


def test_history_skips_blank_and_malformed_lines(tmp_path):
    path = _log(tmp_path)
    asklog.record_ask(_entry(question="iyi soru"), path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n   \n{bozuk satır\n42\n")
    asklog.record_ask(_entry(question="iyi soru 2"), path)
    items = asklog.history(path)
    assert [item["question"] for item in items] == ["iyi soru 2", "iyi soru"]


def test_history_of_missing_file_is_empty(tmp_path):
    assert asklog.history(_log(tmp_path)) == []


# ------------------------------------------------------------------ find_ask


def test_find_ask_returns_the_stored_record(tmp_path):
    path = _log(tmp_path)
    entry = _entry(audit_id=asklog.new_audit_id())
    asklog.record_ask(entry, path)
    found = asklog.find_ask(entry["audit_id"], path)
    assert found["source"] == "web"
    assert found["sql"] == entry["sql"]
    assert found["row_count"] == 1


def test_find_ask_skips_malformed_lines(tmp_path):
    path = _log(tmp_path)
    entry = _entry()
    asklog.record_ask(entry, path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{bozuk satır\n")
    found = asklog.find_ask(entry["audit_id"], path)
    assert found["audit_id"] == entry["audit_id"]


def test_find_ask_unknown_id_is_none(tmp_path):
    path = _log(tmp_path)
    asklog.record_ask(_entry(), path)
    assert asklog.find_ask("yokboylebirkimlik", path) is None


def test_find_ask_missing_file_is_none(tmp_path):
    assert asklog.find_ask("abc123abc123", _log(tmp_path)) is None
