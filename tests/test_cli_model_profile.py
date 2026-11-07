# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""``--model`` ve ``--models-file`` (T150, PLAN R4-10/R4-12/R4-14): koşum bir profili olsun.

Bir profil uç noktayı, model adını, anahtarın hangi ortam değişkeninde durduğunu ve kaç tokenlık
bir pencereyle koşulduğunu söyler. Ekran hangi modelle ve hangi bütçeyle koşulduğunu ilk satırlarda
söyler, ``--mode auto``nun eşiği o pencereden kurulur (yarısı: araç turlarının payı), rapor da
koşumu onunla yazar. Profil söylenmediğinde koşum Run 3'ün halidir: config'in ucu, bütçe yok,
imzada ``budget`` anahtarı yok. Testler profil dosyasını kendi tmp klasöründe kurar; böylece
gerçek ``config/models.json``daki anahtar değişkenlerine de o uç noktalara da dokunulmaz.
"""

import json
from pathlib import Path

import pytest

from nl2sql import config
from nl2sql.cli import main as cli

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
QUESTION = "Cari kartlarında kaç kayıt var?"
# Run 3'ün imzası: ``budget`` yalnız --model bir bütçe verdiğinde yazılır (R4-10).
RUN3_KEYS = {
    "mode",
    "llm",
    "model",
    "question_ids",
    "golden_hash",
    "schema_hash",
    "rules_hash",
    "index_hash",
    "max_tool_calls",
    "dataset",
}
KEY_ENV = "NL2SQL_TEST_EKSIK_ANAHTAR"


def models_file(tmp_path) -> Path:
    """İki pencere ve bir eksiği olan dosya: 256K sığar, 1024 token ilk tura bile yetmez."""
    path = tmp_path / "models.json"
    path.write_text(
        json.dumps(
            {
                "profiles": {
                    "genis": {
                        "base_url": "http://127.0.0.1:9/v1",
                        "model": "denek-27b",
                        "context_budget": 262144,
                        "max_output_tokens": 8192,
                    },
                    "kisa": {
                        "base_url": "http://127.0.0.1:9/v1",
                        "model": "denek-27b",
                        "context_budget": 1024,
                        "max_output_tokens": 512,
                    },
                    "sir": {
                        "base_url": "http://127.0.0.1:9/v1",
                        "model": "denek-27b",
                        "api_key_env": KEY_ENV,
                        "context_budget": 8192,
                        "max_output_tokens": 1024,
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def project(tmp_path, monkeypatch, capsys):
    """Proje kökü geçici: kümenin veritabanı, indeksi ve raporu repoya düşmez."""
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(FIXTURE_ROOT))
    assert cli.build_database(dataset="mini") == 0
    assert cli.build_index("fake", dataset="mini") == 0
    capsys.readouterr()
    return tmp_path


def report_of(tmp_path, mode: str = "full") -> dict:
    """Koşunun raporu: kümenin kendi ``eval_out``u altına, modun klasörüne (R2-12, R4-3)."""
    run = tmp_path / "eval_out" / "mini" / mode / "latest" / "report.json"
    return json.loads(run.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ ask: hangi modelle koştuğu


def test_ask_names_the_profile_and_its_window(project, capsys):
    code = cli.main(
        [
            "ask",
            QUESTION,
            "--llm",
            "fake",
            "--dataset",
            "mini",
            "--model",
            "genis",
            "--models-file",
            str(models_file(project)),
        ]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert "Model: genis (denek-27b, bütçe 262.144 token)" in out
    assert "Mod: auto -> full_rules (bağlam tahmini " in out
    assert "· bütçe 131.072)" in out, "eşik pencerenin yarısıdır (R4-12)"


@pytest.mark.parametrize(
    "profile, mode, budget",
    [("genis", "full_rules", "131.072"), ("kisa", "rag", "512")],
)
def test_auto_uses_the_profile_window(project, profile, mode, budget, capsys):
    """Aynı şema iki pencerede iki farklı mod: 256K'ya tam kurallı istem sığar, 1024 tokena sığmaz."""
    cli.main(
        [
            "ask",
            QUESTION,
            "--llm",
            "fake",
            "--dataset",
            "mini",
            "--model",
            profile,
            "--models-file",
            str(models_file(project)),
        ]
    )
    out = capsys.readouterr().out

    assert f"Mod: auto -> {mode} (bağlam tahmini " in out
    assert f"· bütçe {budget})" in out


def test_a_profile_without_a_model_keeps_the_plain_mode_line(project, capsys):
    cli.main(["ask", QUESTION, "--llm", "fake", "--dataset", "mini", "--mode", "full"])
    out = capsys.readouterr().out

    assert "Model:" not in out and "bütçe" not in out


# ------------------------------------------------------------------ eval: ölçüm profilin penceresiyle


def test_eval_measures_with_the_profile_budget(project, capsys):
    code = cli.main(
        [
            "eval",
            "--llm",
            "fake",
            "--dataset",
            "mini",
            "--model",
            "kisa",
            "--models-file",
            str(models_file(project)),
        ]
    )
    out = capsys.readouterr().out
    data = report_of(project)

    assert code == 0
    assert "context_overflow" in out, "canlı satır taşmayı diğer outcome'lar gibi söyler"
    assert data["profile"] == {
        "name": "kisa",
        "model": "denek-27b",
        "context_budget": 1024,
        "max_output_tokens": 512,
    }
    assert data["context"]["overflows"] == len(data["questions"]) == 3
    assert data["context"]["peak_estimate"] > 512
    assert data["config"]["fingerprint"]["budget"] == 512
    assert data["model"] == "fake", "--llm fake profili değil kaydı oynatır"
    markdown = (project / "eval_out" / "mini" / "full" / "latest" / "report.md").read_text(
        encoding="utf-8"
    )
    assert "- Model profili: kisa · bütçe 1024" in markdown


def test_a_wide_profile_reports_no_overflow(project, capsys):
    cli.main(
        [
            "eval",
            "--llm",
            "fake",
            "--dataset",
            "mini",
            "--model",
            "genis",
            "--models-file",
            str(models_file(project)),
        ]
    )
    capsys.readouterr()
    data = report_of(project)

    assert data["score"] == {"passed": 3, "total": 3}
    assert data["context"]["overflows"] == 0 and data["context"]["peak_estimate"] > 0
    assert data["config"]["fingerprint"]["budget"] == 253952


# ------------------------------------------------------------------ hatalar


def test_an_unknown_profile_lists_the_known_ones(project, capsys):
    code = cli.main(
        [
            "ask",
            QUESTION,
            "--llm",
            "fake",
            "--dataset",
            "mini",
            "--model",
            "gpt-5",
            "--models-file",
            str(models_file(project)),
        ]
    )
    out = capsys.readouterr().out

    assert code == 2
    assert out.strip() == (
        "Bilinmeyen model profili: gpt-5 (bilinenler: genis, kisa, sir)"
    ), "tek satır: ne istendi ve bilinenler"
    assert "Traceback" not in out


def test_a_missing_models_file_says_which_path(project, capsys):
    code = cli.main(
        [
            "eval",
            "--llm",
            "fake",
            "--dataset",
            "mini",
            "--model",
            "genis",
            "--models-file",
            str(project / "yok.json"),
        ]
    )
    out = capsys.readouterr().out

    assert code == 2
    assert "Model profili dosyası yok:" in out and "yok.json" in out
    assert "Traceback" not in out and not (project / "eval_out").exists()


def test_a_missing_key_variable_names_the_variable_to_define(project, monkeypatch, capsys):
    monkeypatch.delenv(KEY_ENV, raising=False)
    code = cli.main(
        [
            "ask",
            QUESTION,
            "--llm",
            "openai",
            "--dataset",
            "mini",
            "--model",
            "sir",
            "--models-file",
            str(models_file(project)),
        ]
    )
    out = capsys.readouterr().out

    assert code == 2
    # Küme satırı her halükarda ilk satırdır (R4-14); arıza onun altındaki tek satırdır.
    assert out.splitlines()[-1] == f"API anahtarı yok: {KEY_ENV} ortam değişkenini tanımlayın."
    assert "Traceback" not in out and "Strata" not in out


# ------------------------------------------------------------------ --model yoksa Run 3


def test_without_a_model_the_fingerprint_has_no_budget(project, capsys):
    code = cli.main(["eval", "--llm", "fake", "--dataset", "mini"])
    out = capsys.readouterr().out
    data = report_of(project)

    assert code == 0
    assert set(data["config"]["fingerprint"]) == RUN3_KEYS
    assert "profile" not in data
    assert "Model:" not in out and "bütçe" not in out
