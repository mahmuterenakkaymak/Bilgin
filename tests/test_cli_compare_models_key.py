# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""``eval --compare --models`` ``llm.ping``in sebebini ezmez (T162, PLAN R4-10; T151'in kapısı).

``UNSLOTH_API_KEY`` tanımlı değilken blok "GPU'da bu modeli açıp yeniden koşun" tavsiyesiyle
atlanıyordu; oysa uç nokta açıktı, eksik olan anahtar değişkeniydi. Artık profilin
``api_key_env``inde tanımsız bir değişken varsa hem raporun ``skipped`` hanesi hem ⚠ satırı o
cümleyi taşır; kapalı uç noktanın MODEL_SKIPPED metni bayt bayt durur. Gerçek yoklama hiç
kullanılmaz: stub ``anahtarsiz`` için anahtar cümlesini, ``kapali`` için uç nokta sebebini döndürür.
Koşan bir model varsa kod 0 ve rapor yazılır; hiç koşmayan varsa rapor yazılmadan kod 3 çıkar.
"""

import json
from pathlib import Path

import pytest

from bilgin import config
from bilgin.cli import main as cli

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
CLOSED = "http://127.0.0.1:9/v1"  # discard portu: hiçbir zaman yanıt vermez
KEY_ENV = "BILGIN_TEST_ANAHTAR_YOK"
KEY_SENTENCE = f"API anahtarı yok: {KEY_ENV} ortam değişkenini tanımlayın."
DOWN_REASON = f"uç nokta yanıt vermiyor ({CLOSED})"  # stub'un döndüğü gerçek yoklama sebebi


def models_file(tmp_path) -> Path:
    """Üç profil: anahtar değişkeni tanımsız, uç noktası kapalı, ikisi de olmayan koşar."""
    profile = {
        "base_url": CLOSED,
        "model": "qwen27b",
        "context_budget": 262144,
        "max_output_tokens": 8192,
    }
    path = tmp_path / "models.json"
    path.write_text(
        json.dumps(
            {
                "profiles": {
                    "anahtarsiz": {**profile, "api_key_env": KEY_ENV},
                    "kapali": profile,
                    "saglam": profile,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def project(tmp_path, monkeypatch, capsys):
    """Proje kökü geçici, anahtar değişkeni yok: tıpkı UNSLOTH_API_KEY tanımlı değilken."""
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(FIXTURE_ROOT))
    monkeypatch.delenv(KEY_ENV, raising=False)
    assert cli.build_database(dataset="mini") == 0
    assert cli.build_index("fake", dataset="mini") == 0
    capsys.readouterr()
    return tmp_path


def ping_stub():
    """Gerçek yoklamanın yerini alan stub; kapalı bir porta da anahtar sormaya da gerek kalmaz."""

    def ping(profile):
        if profile.name == "anahtarsiz":
            return KEY_SENTENCE
        if profile.name == "kapali":
            return DOWN_REASON
        return None

    return ping


def run(project, models, **kwargs):
    return cli.compare_models_cmd(
        models=models,
        dataset="mini",
        models_file=str(models_file(project)),
        llm_kind="openai",
        modes=["full_rules"],
        **kwargs,
    )


def report_data(project) -> dict:
    return json.loads(next(project.rglob("compare_mini_*.json")).read_text(encoding="utf-8"))


def test_a_missing_key_variable_is_skipped_with_its_own_sentence(project, capsys):
    code = run(project, ["anahtarsiz", "kapali", "saglam"], ping=ping_stub())
    out = capsys.readouterr().out
    data = report_data(project)

    assert code == 0, "koşan bir model varsa karşılaştırma tamamlanmıştır"
    assert list(data["cells"]) == ["saglam"], "koşmayan modelin hücresi uydurulmaz"
    assert data["skipped"]["anahtarsiz"] == KEY_SENTENCE
    assert data["skipped"]["kapali"] == cli.MODEL_SKIPPED.format(url=CLOSED)
    # Ekranda da aynı iki sebep: eksik anahtar "modeli aç" tavsiyesini asla almaz.
    assert f"⚠ anahtarsiz: {KEY_SENTENCE}\n" in out
    assert f"⚠ kapali: {cli.MODEL_SKIPPED.format(url=CLOSED)}\n" in out


def test_no_model_ran_writes_no_report(project, capsys):
    code = run(project, ["anahtarsiz", "kapali"], ping=ping_stub())
    out = capsys.readouterr().out

    assert code == 3
    assert f"⚠ anahtarsiz: {KEY_SENTENCE}\n" in out
    assert f"⚠ kapali: {cli.MODEL_SKIPPED.format(url=CLOSED)}\n" in out
    assert not list(project.rglob("compare_mini_*.json")), "koşulmamış bloğun raporu yazılmaz"
