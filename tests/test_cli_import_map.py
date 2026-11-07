# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T84: import-map komutu — öneriyi göster, eşlemeyi diske bırak, --accept ile şemayı yaz.

Kitap da eşleme de şema da tmp klasörde, yani test repoya hiçbir şey yazmaz. Model burada FakeLLM
ve ``--llm fake`` sözlük eşlemesini JSON olarak geri veren sahte istemcidir: ölçülen şey önerinin
zekâsı değil öneri → dosya → dönüşüm boru hattının kendisidir (R3-2).
"""

import json

import openpyxl

from nl2sql.agent.fake import FakeLLM
from nl2sql.agent.llm import ChatResponse
from nl2sql.cli import main as cli
from nl2sql.schema_map import excel

HEADERS = ["TABLO", "KOLON", "TİP", "AÇIKLAMA", "REFERANS", "DEĞER", "NULL", "MODÜL"]


def row(table="", column="", tip="", aciklama="", referans="", deger="", bos="", modul=""):
    return [table, column, tip, aciklama, referans, deger, bos, modul]


def workbook(tmp_path, rows, headers=HEADERS, name="KOLONLAR", title=False):
    """Geçici kitap; ``title`` başlığı 3. satıra taşır (üstte dosya adı ve boş satır)."""
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = name
    if title:
        sheet.append(["MÜŞTERİ ŞEMA HARİTASI"])
        sheet.append([])
    sheet.append(headers)
    for item in rows:
        sheet.append(item)
    path = tmp_path / "harita.xlsx"
    book.save(path)
    return path


def fake_llm(preview):
    return cli.make_map_client("fake", preview)


def run(path, tmp_path, **kwargs):
    """Komutun gerçek girdisi: ``--llm fake``in istemcisi öndenizden üretilir, yollar tmp'de."""
    return cli.import_map(
        path,
        fake_llm,
        proposal_path=tmp_path / "mapping.json",
        out=tmp_path / "imported.json",
        **kwargs,
    )


def mapping_file(tmp_path) -> dict:
    return json.loads((tmp_path / "mapping.json").read_text(encoding="utf-8"))


def schema_file(tmp_path) -> dict:
    return json.loads((tmp_path / "imported.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ öneri


def test_propose_prints_the_table_and_writes_the_mapping(tmp_path, capsys):
    path = workbook(tmp_path, [row("TBLA", "KOD", "int", "Kartın kodu", modul="Stok")])
    assert run(path, tmp_path) == 0

    out = capsys.readouterr().out
    assert "KOLONLAR — başlık satırı 1" in out
    assert "table_name" in out and "data_type" in out and "module" in out
    assert str(tmp_path / "mapping.json") in out and "--accept" in out
    assert (tmp_path / "mapping.json").exists()
    assert not (tmp_path / "imported.json").exists(), "--accept olmadan şema yazılmaz"


def test_the_written_mapping_is_the_one_convert_reads(tmp_path):
    path = workbook(tmp_path, [row("TBLA", "KOD", "int")])
    run(path, tmp_path)

    mapping = mapping_file(tmp_path)
    assert mapping["generated_by"] == "llm" and mapping["disagreements"] == []
    assert [item["column"] for item in mapping["sheets"][0]["columns"]] == HEADERS
    assert mapping["sheets"][0]["columns"][0]["table_name"] == "TABLO"
    assert mapping["sheets"][0]["columns"][2]["data_type"] == "TİP"


def test_a_header_that_maps_to_nothing_stays_visible(tmp_path, capsys):
    path = workbook(tmp_path, [row("TBLA", "KOD", "int")], headers=[*HEADERS, "NOT"])
    run(path, tmp_path)

    out = capsys.readouterr().out
    assert "NOT" in out and "hiçbir alan" in out


def test_disagreement_between_the_model_and_the_dictionary_is_shown(tmp_path, capsys):
    path = workbook(tmp_path, [row("TBLA", "KOD", "int", "Kartın kodu")])
    claim = {
        "sheets": [
            {"sheet": "KOLONLAR", "columns": [{"column": "AÇIKLAMA", "table_name": "AÇIKLAMA"}]}
        ]
    }
    scripted = FakeLLM([ChatResponse(content=json.dumps(claim, ensure_ascii=False))])
    assert cli.import_map(
        path,
        lambda preview: scripted,
        proposal_path=tmp_path / "m.json",
        out=tmp_path / "s.json",
    ) == 0

    out = capsys.readouterr().out
    assert "⚠ uyuşmuyor: KOLONLAR.AÇIKLAMA table_name: llm=AÇIKLAMA fallback=-" in out
    assert "⚠ uyuşmuyor: KOLONLAR.AÇIKLAMA description: llm=- fallback=AÇIKLAMA" in out


# ------------------------------------------------------------------ --accept


def test_accept_converts_every_row_and_writes_the_schema(tmp_path, capsys):
    path = workbook(tmp_path, [row("TBLA", "KOD", "int"), row("TBLB", "AD", "metin")])
    assert run(path, tmp_path, accept=True) == 0

    assert [item["name"] for item in schema_file(tmp_path)["tables"]] == ["TBLA", "TBLB"]
    assert (
        f"Şema yazıldı: {tmp_path / 'imported.json'} (2 tablo, 2 kolon, 0 atlanan satır)"
        in capsys.readouterr().out
    )


def test_skipped_rows_are_listed_with_sheet_and_row(tmp_path, capsys):
    path = workbook(
        tmp_path,
        [row(column="KOD", tip="int"), row("TBLA", "AD", "garip")],
        title=True,
    )
    assert run(path, tmp_path, accept=True) == 0

    out = capsys.readouterr().out
    assert "(1 tablo, 1 kolon, 2 atlanan satır)" in out
    assert "KOLONLAR.satır 4: TABLO boş" in out
    assert "KOLONLAR.satır 5: tip 'garip' tanınmadı" in out


def test_accept_with_an_edited_mapping_never_asks_the_model(tmp_path, capsys):
    path = workbook(tmp_path, [row("TBLA", "KOD", "int")])
    edited = tmp_path / "benim.json"
    edited.write_text(
        json.dumps(
            {
                "sheets": [
                    {
                        "sheet": "KOLONLAR",
                        "columns": [
                            {"column": "TABLO", "table_name": "TABLO"},
                            {"column": "KOLON", "column_name": "KOLON"},
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def no_model(preview):
        raise AssertionError("--mapping verilmişse model aranmaz")

    assert (
        cli.import_map(
            path,
            no_model,
            accept=True,
            mapping=edited,
            proposal_path=tmp_path / "yazilmaz.json",
            out=tmp_path / "imported.json",
        )
        == 0
    )
    assert [item["name"] for item in schema_file(tmp_path)["tables"][0]["columns"]] == ["KOD"]
    assert not (tmp_path / "yazilmaz.json").exists(), "elle verilen eşleme önerinin üstüne yazılmaz"
    assert f"Eşleme: {edited} (dosya)" in capsys.readouterr().out


# ------------------------------------------------------------------ arıza


def test_missing_file_exits_2_without_a_traceback(tmp_path, capsys):
    assert cli.import_map(tmp_path / "yok.xlsx", fake_llm) == 2

    out = capsys.readouterr().out
    assert "Excel dosyası yok" in out and "yok.xlsx" in out and "Traceback" not in out


def test_unreadable_mapping_exits_2(tmp_path, capsys):
    path = workbook(tmp_path, [row("TBLA", "KOD", "int")])
    broken = tmp_path / "bozuk.json"
    broken.write_text('{"sheets": [', encoding="utf-8")

    code = cli.import_map(
        path, fake_llm, accept=True, mapping=broken, out=tmp_path / "imported.json"
    )
    assert code == 2
    assert "Eşleme dosyası okunamadı" in capsys.readouterr().out
    assert not (tmp_path / "imported.json").exists()


# ------------------------------------------------------------------ boru hattı


def test_fake_map_client_answers_with_the_dictionary_mapping():
    preview = {
        "file": "h.xlsx",
        "sheets": [{"name": "K", "header_row": 1, "headers": ["TABLO", "KOLON"], "rows": []}],
    }
    reply = cli.make_map_client("fake", preview).chat([{"role": "user", "content": "{}"}])
    assert json.loads(reply.content) == excel.fallback_mapping(preview)


def test_main_routes_import_map(monkeypatch):
    seen = {}

    def capture(path, llm_factory, **kwargs):
        seen["path"] = path
        seen["client"] = llm_factory({"file": "h.xlsx", "sheets": []})
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "import_map", capture)
    argv = [
        "import-map",
        "harita.xlsx",
        "--llm",
        "fake",
        "--accept",
        "--mapping",
        "m.json",
        "--out",
        "c.json",
    ]
    assert cli.main(argv) == 0
    assert seen["path"] == "harita.xlsx" and isinstance(seen["client"], FakeLLM)
    assert seen["accept"] is True and seen["mapping"] == "m.json" and seen["out"] == "c.json"
