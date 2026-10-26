"""T81: modelden başlık eşleme önerisi - doğrulama, sözlükle birleşme, uyuşmazlıklar.

Model burada FakeLLM: öneri hazır bir JSON, ulaşılmayan endpoint de bir script. Böylece
önerinin kabulü, bilinmeyen sayfa/sütunun düşmesi ve yedeğe düşme model olmadan test edilir.
"""

import json

from nl2sql.agent.fake import FakeLLM, unreachable
from nl2sql.agent.llm import ChatResponse
from nl2sql.schema_map.excel import fallback_mapping, propose

HEADERS = ["TABLO", "KOLON", "TİP", "AÇIKLAMA"]
ROWS = [["TBLSTHAR", "STHAR_GCKOD", "VARCHAR", "Giriş/çıkış kodu"]]

# ASSUMPTION: R6-13 ile eşleme kaydı üç alan daha taşıyor (pii/deny/keywords); öneri yine sekizini
# iddia eder, ama kaydın anahtar kümesi _FIELDS'ın tamamıdır.
FIELDS = (
    "table_name",
    "column_name",
    "data_type",
    "description",
    "fk_target",
    "values",
    "nullable",
    "module",
    "pii",
    "deny",
    "keywords",
)


def preview(headers=HEADERS, rows=ROWS, name="KOLONLAR", file="müşteri_harita.xlsx") -> dict:
    return {
        "file": file,
        "sheets": [
            {
                "name": name,
                "header_row": 1,
                "headers": list(headers),
                "rows": [list(row) for row in rows],
            }
        ],
    }


def proposal(columns, name="KOLONLAR") -> dict:
    return {"sheets": [{"sheet": name, "columns": list(columns)}]}


def column(ref: str, *fields) -> dict:
    """Bir sütun önerisi: adı geçen alanlar başlık metniyle dolar, ötekiler null."""
    return {"column": ref, **{name: (ref if name in fields else None) for name in FIELDS}}


def asks(payload: dict, preview_map: dict | None = None) -> dict:
    reply = json.dumps(payload, ensure_ascii=False)
    return propose(preview() if preview_map is None else preview_map, scripted(reply))


def scripted(content: str) -> FakeLLM:
    return FakeLLM([ChatResponse(content=content)])


def entry(mapping: dict, column_name: str, sheet: int = 0) -> dict:
    for item in mapping["sheets"][sheet]["columns"]:
        if item["column"] == column_name:
            return item
    raise AssertionError(f"'{column_name}' sütunu mapping'de yok: {mapping['sheets'][sheet]}")


def filled(item: dict) -> list[str]:
    return [name for name, value in item.items() if name != "column" and value is not None]


def test_correct_proposal_is_accepted():
    mapping = asks(
        proposal(
            [
                column("TABLO", "table_name"),
                column("KOLON", "column_name"),
                column("TİP", "data_type"),
                column("AÇIKLAMA", "description"),
            ]
        )
    )
    assert mapping["generated_by"] == "llm"
    assert mapping["disagreements"] == []
    assert [filled(entry(mapping, header)) for header in HEADERS] == [
        ["table_name"],
        ["column_name"],
        ["data_type"],
        ["description"],
    ]
    assert entry(mapping, "TABLO")["table_name"] == "TABLO"


def test_mapping_shape_and_sheet_metadata():
    mapping = asks(proposal([], name="SHEET-1"), preview(name="SHEET-1", file="a.xlsx"))
    assert mapping["file"] == "a.xlsx"
    assert mapping["generated_by"] == "llm"
    assert [(s["sheet"], s["header_row"]) for s in mapping["sheets"]] == [("SHEET-1", 1)]


def test_missing_field_keys_stay_null_and_the_dictionary_survives():
    mapping = asks(proposal([{"column": "TABLO"}, column("KOLON", "column_name")]))
    for item in mapping["sheets"][0]["columns"]:
        assert set(item) == {"column", *FIELDS}
    assert filled(entry(mapping, "TABLO")) == ["table_name"]
    assert filled(entry(mapping, "AÇIKLAMA")) == ["description"]


def test_wrong_table_name_shows_a_disagreement():
    mapping = asks(
        proposal(
            [
                column("TABLO", "table_name"),
                column("KOLON", "column_name"),
                column("TİP", "data_type"),
                column("AÇIKLAMA", "table_name"),
            ]
        )
    )
    assert filled(entry(mapping, "AÇIKLAMA")) == ["table_name"], "öneri uygulanır, sessizce düzeltilmez"
    assert {d["field"]: (d["llm"], d["fallback"]) for d in mapping["disagreements"]} == {
        "table_name": ("AÇIKLAMA", None),
        "description": (None, "AÇIKLAMA"),
    }
    for note in mapping["disagreements"]:
        assert set(note) == {"sheet", "column", "field", "llm", "fallback"}
        assert note["sheet"] == "KOLONLAR"
        assert note["column"] == "AÇIKLAMA"


def test_prompt_carries_only_sheet_names_headers_and_preview_rows():
    seen = []

    def script(messages):
        seen.append(messages)
        return [ChatResponse(content=json.dumps(proposal([]), ensure_ascii=False))]

    propose(preview(), FakeLLM(script))
    assert [message["role"] for message in seen[0]] == ["system", "user"]
    assert json.loads(seen[0][1]["content"]) == {
        "sheets": [{"name": "KOLONLAR", "headers": HEADERS, "rows": ROWS}]
    }
    assert "müşteri_harita.xlsx" not in "".join(m["content"] for m in seen[0])


def test_code_fence_and_prose_around_the_json_are_tolerated():
    body = json.dumps(proposal([column("TABLO", "table_name")]), ensure_ascii=False)
    mapping = propose(
        preview(),
        scripted(f"İşte önerim:\n```json\n{body}\n```\nBaşka bir sorunuz olursa yazın."),
    )
    assert mapping["generated_by"] == "llm"
    assert filled(entry(mapping, "TABLO")) == ["table_name"]


def test_unreachable_llm_returns_the_pure_fallback(capsys):
    mapping = propose(preview(), FakeLLM(unreachable()))
    assert mapping == fallback_mapping(preview())
    assert mapping["generated_by"] == "fallback"
    out = capsys.readouterr().out
    assert "başlık sözlüğüyle ilerleniyor" in out
    assert "127.0.0.1:9" in out, "not hangi hatanın yedeğe düşürdüğünü de söylemeli"


def test_reply_without_json_returns_the_pure_fallback(capsys):
    mapping = propose(preview(), scripted("Bu başlıkları eşleştiremedim, kusura bakmayın."))
    assert mapping == fallback_mapping(preview())
    assert "JSON" in capsys.readouterr().out


def test_unknown_sheet_is_dropped_with_a_note(capsys):
    mapping = asks(
        {
            "sheets": [
                {"sheet": "TABLOLAR", "columns": [column("TABLO", "module")]},
                {"sheet": "KOLONLAR", "columns": [column("KOLON", "column_name")]},
            ]
        }
    )
    assert filled(entry(mapping, "KOLON")) == ["column_name"]
    assert filled(entry(mapping, "TABLO")) == ["table_name"], "bilinmeyen sayfa öneriyi bozmaz"
    out = capsys.readouterr().out
    assert "TABLOLAR" in out and "düşürüldü" in out


def test_unknown_column_is_dropped_with_a_note(capsys):
    mapping = asks(proposal([column("GIZLI", "description"), column("TİP", "data_type")]))
    assert filled(entry(mapping, "TİP")) == ["data_type"]
    assert mapping["disagreements"] == []
    out = capsys.readouterr().out
    assert "GIZLI" in out and "düşürüldü" in out


def test_column_letter_names_a_headerless_column():
    mapping = asks(proposal([column("B", "description")]), preview(headers=["TABLO", "", "KOLON"]))
    assert filled(entry(mapping, "B")) == ["description"]
    assert mapping["disagreements"] == []


def test_llm_may_add_a_field_the_dictionary_does_not_know():
    mapping = asks(
        proposal([column("KOD_AÇILIMI", "description")]),
        preview(headers=["TABLO", "KOD_AÇILIMI"]),
    )
    assert filled(entry(mapping, "KOD_AÇILIMI")) == ["description"]
    assert mapping["disagreements"] == [], "sözlük suskunken uyuşmazlıktan söz edilmez"


def test_every_sheet_keeps_its_own_columns_in_preview_order():
    both = {
        "file": "cift.xlsx",
        "sheets": [
            {"name": "TABLOLAR", "header_row": 1, "headers": ["TABLO", "MODÜL"], "rows": []},
            {"name": "KOLONLAR", "header_row": 1, "headers": ["KOLON", "TİP"], "rows": []},
        ],
    }
    mapping = asks(
        {
            "sheets": [
                {"sheet": "KOLONLAR", "columns": [column("TİP", "values")]},
                {"sheet": "TABLOLAR", "columns": [column("TABLO", "table_name")]},
            ]
        },
        both,
    )
    assert [sheet["sheet"] for sheet in mapping["sheets"]] == ["TABLOLAR", "KOLONLAR"]
    assert filled(entry(mapping, "TİP", 1)) == ["values"]
    assert filled(entry(mapping, "MODÜL")) == ["module"]
    assert {(d["sheet"], d["column"], d["field"]) for d in mapping["disagreements"]} == {
        ("KOLONLAR", "TİP", "data_type"),
        ("KOLONLAR", "TİP", "values"),
    }
