"""T412: ``eval --lang`` — ölçümün dili, koşulan soruların dilidir (PLAN R8-11).

İki şey birlikte çevrilir: hangi soruların koştuğu (``dataset.golden(lang)``) ve koşumun kendi
cümleleri. Canlı satır, skor/metrik bloğu ve report.md ``eval.*`` anahtarlarından gelir; outcome
kodları (``pass``, ``wrong_result`` ...) raporun kendi sözlüğüdür, iki dilde de İngilizce kalır.
report.json hangi dille yazıldığını ``lang`` alanıyla kendisi söyler.

Dünya gerçek ``load_dataset("wwi")``: kümenin kendi builder'ının tmp'de kurduğu dosya, gerçek
``cli.evaluate`` ve ``cli.make_client("fake")``ın her iki dilin altın kaydını da oynatan hali.
İngilizce altın kümenin soruları İngilizce olduğu için report.md'de Türkçe harfli tek satır
olmamalıdır; ekranda ise kümenin görünen adı bir veri değeridir, o yüzden çevrilmez.
"""

import json

import pytest
from pytest import MonkeyPatch

from nl2sql.cli import main as cli
from nl2sql.datasets import load_dataset
from nl2sql.eval import report, runner
from nl2sql.i18n.detect import TURKISH_LETTERS
from nl2sql.i18n.scan import user_literals

WWI = load_dataset("wwi")
ENGLISH = WWI.golden("en")
TOTAL = len(ENGLISH)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Modül boyunca tek kurulum: wwi builder'ının dosyası ve audit'i tek tmp klasörde.

    Kabukta ambiyans duran ``NL2SQL_MSSQL_CONN``/``NL2SQL_BACKEND`` silinir: küme SQLite'ı kendi
    taşır (R7-29), yani ölçümün kapısı hiçbir zaman canlı sunucuya dönmez.
    """
    root = tmp_path_factory.mktemp("eval-lang")
    mp = MonkeyPatch()
    mp.delenv("NL2SQL_MSSQL_CONN", raising=False)
    mp.delenv("NL2SQL_BACKEND", raising=False)
    database = root / "wwi.db"
    WWI.build_db(db_path=database, sql_path=root / "wwi.sql")
    try:
        yield database, root / "audit.jsonl"
    finally:
        mp.undo()


def run(world, tmp_path, lang=None):
    """Tek koşum; ``lang`` söylenmediğinde ``evaluate``ın kendi varsayılanı koşar.

    Rapor klasörü dile göre ayrılır, yani ikinci koşum birincinin ``latest``ini okuyup delta
    bölümü üretmez - iki rapor birbirinin devamı değildir.
    """
    database, audit = world
    out_dir = tmp_path / f"eval_out-{lang or 'tr'}"
    code = cli.evaluate(
        cli.make_client("fake", "full", WWI),
        mode="full",
        db_path=database,
        audit_path=audit,
        out_dir=out_dir,
        dataset="wwi",
        **({} if lang is None else {"lang": lang}),
    )
    return code, out_dir


def written(out_dir) -> dict:
    return json.loads((out_dir / "latest" / "report.json").read_text(encoding="utf-8"))


def markdown(out_dir) -> str:
    return (out_dir / "latest" / "report.md").read_text(encoding="utf-8")


def turkish(text: str) -> list[str]:
    """Metnin hâlâ Türkçe harf taşıyan satırları - çevirinin ölçütü budur."""
    return [line for line in text.splitlines() if any(ch in TURKISH_LETTERS for ch in line)]


def made(outcome: str) -> runner.QuestionResult:
    """Satır biçiminin sahte sorusu: çevrilen tek şey etiketler, outcome kodu değil."""
    return runner.QuestionResult(
        id="Q03", question="Soru?", outcome=outcome, tool_calls=3, total_tokens=900, seconds=1.0
    )


# ------------------------------------------------------------------ İngilizce koşum


def test_the_english_run_measures_the_english_golden_set(world, tmp_path, capsys):
    code, out_dir = run(world, tmp_path, "en")
    data = written(out_dir)

    assert code == 0
    assert data["lang"] == "en"
    assert data["score"] == {"passed": TOTAL, "total": TOTAL}
    assert [question["question"] for question in data["questions"]] == [
        line["question"] for line in ENGLISH
    ]
    assert {question["outcome"] for question in data["questions"]} == {"pass"}


def test_the_english_markdown_has_no_turkish_letter(world, tmp_path, capsys):
    _, out_dir = run(world, tmp_path, "en")
    text = markdown(out_dir)

    # Sorular, SQL ve etiket adları da İngilizce: wwi'nin İngilizce kümesinde veri de çevrilidir.
    assert turkish(text) == []
    assert f"# Evaluation report — fake" in text
    assert f"## Score: {TOTAL}/{TOTAL}" in text
    assert "| Accuracy | 100.00% |" in text and "| Question | Outcome |" in text


def test_the_english_screen_follows_the_lang(world, tmp_path, capsys):
    code, out_dir = run(world, tmp_path, "en")
    out = capsys.readouterr().out

    assert code == 0
    assert "Mode: full" in out and f"Score: {TOTAL}/{TOTAL}" in out
    assert out.count(" tools ") == TOTAL and "Report: " in out
    assert out.rstrip().endswith("report.md"), "son satır raporun yolu"
    # Kümenin görünen adı kümenin verisidir: İngilizce koşumda da olduğu gibi yazılır.
    assert [line for line in turkish(out) if "Dataset:" not in line] == []


# ------------------------------------------------------------------ Türkçe koşum bugün neyse o


def test_the_turkish_run_is_todays_report(world, tmp_path, capsys):
    code, out_dir = run(world, tmp_path)
    data = written(out_dir)
    text = markdown(out_dir)
    out = capsys.readouterr().out

    assert code == 0 and data["lang"] == "tr"
    assert f"## Skor: {TOTAL}/{TOTAL}" in text and "**Devam" in text
    assert "| Doğruluk | %100,00 |" in text and "| Soru | Sonuç | Araç | Token | Süre |" in text
    assert f"Mod: full" in out and f"Skor: {TOTAL}/{TOTAL}" in out
    assert out.count(" araç ") == TOTAL and "Rapor: " in out


# ------------------------------------------------------------------ kodlar çevrilmez


def test_the_outcome_codes_stay_english_in_both_languages():
    for outcome in (*runner.OUTCOMES, *runner.AMBIGUOUS_OUTCOMES):
        assert outcome in runner.progress_line(made(outcome), "en")
        assert outcome in runner.progress_line(made(outcome))


def test_the_progress_line_labels_follow_the_lang():
    assert runner.progress_line(made("pass"), "en").split() == [
        "Q03", "✓", "pass", "3", "tools", "1.0", "s", "900", "tokens"
    ]
    assert runner.progress_line(made("pass")).split() == [
        "Q03", "✓", "pass", "3", "araç", "1.0", "sn", "900", "token"
    ]


def test_the_decision_and_the_metric_labels_are_translated(tmp_path):
    rows = [
        runner.QuestionResult(
            id=f"Q{n:02d}", question="?", outcome="pass", reason="" if n > 1 else "Satırlar farklı."
        )
        for n in range(1, 8)
    ]

    for lang, head, label in (("en", "Continue", "Accuracy"), ("tr", "Devam", "Doğruluk")):
        out_dir = tmp_path / lang
        report.write_report(rows, out_dir, model="fake", lang=lang)
        data, text = written(out_dir), markdown(out_dir)

        assert data["lang"] == lang and data["decision"].startswith(head)
        assert f"**{head}" in text and f"| {label} |" in text
        assert report.metrics_block(data["metrics"], lang)[0].startswith(f"  {label}")
        # Boş SQL'in yerindeki cümle de dildedir: İngilizce raporda "_cevap gönderilmedi_" yazmaz.
        assert ("_no answer submitted_" in text) == (lang == "en")
        assert ("_cevap gönderilmedi_" in text) == (lang == "tr")


# ------------------------------------------------------------------ söz dizimi ve tarama


def test_main_resolves_the_lang_for_the_eval_run(monkeypatch):
    monkeypatch.delenv("NL2SQL_LANG", raising=False)
    monkeypatch.setattr(cli, "evaluate", lambda **kwargs: cli._LANG)

    assert cli.main(["eval", "--llm", "fake", "--dataset", "wwi", "--lang", "en"]) == "en"
    assert cli.main(["eval", "--llm", "fake", "--dataset", "wwi"]) == "tr"


def test_the_eval_modules_have_no_turkish_literal_left():
    assert user_literals("nl2sql/eval/runner.py") == []
    assert user_literals("nl2sql/eval/report.py") == []
