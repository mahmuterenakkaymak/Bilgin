# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""``eval --compare --models``: model x mod hücreleri tek raporda (T152, PLAN R4-13).

İki pencere aynı altın soruları koşar: geniş bütçeli fakeA her moda sığar, dar bütçeli fakeB
hiçbirine sığmaz ve hücreleri taşmayla dolar. Kapalı bir uç nokta modeli bloktan düşürür — ⚠
satırı ekranda, sebebi raporun ``skipped``ında; hepsi düşerse rapor yazılmaz ve kod 3 çıkar.
``--modes`` tek başına söz dizimi hatasıdır. Testler profil dosyasını ve kümenin veritabanını,
indeksini, raporunu kendi tmp klasöründe kurar; gerçek uç noktalara dokunulmaz.
"""

import json
from pathlib import Path

import pytest

from nl2sql import config
from nl2sql.cli import main as cli

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
CLOSED = "http://127.0.0.1:9/v1"  # discard portu: hiçbir zaman yanıt vermez


def models_file(tmp_path) -> Path:
    """fakeA 256K'ya sığar, fakeB 1024 tokenlık pencerede ilk tura bile sığamaz."""
    path = tmp_path / "models.json"
    path.write_text(
        json.dumps(
            {
                "profiles": {
                    "fakeA": {
                        "base_url": CLOSED,
                        "model": "genis-27b",
                        "context_budget": 262144,
                        "max_output_tokens": 8192,
                    },
                    "fakeB": {
                        "base_url": CLOSED,
                        "model": "kisa-27b",
                        "context_budget": 1024,
                        "max_output_tokens": 512,
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


def run(project, models, **kwargs):
    """Karşılaştırmayı mini kümeyle koşar; db/indeks/rapor yolunu kümenin kendisi verir (R4-4)."""
    return cli.compare_models_cmd(
        models=models, dataset="mini", models_file=str(models_file(project)), **kwargs
    )


def report_data(project) -> dict:
    return json.loads(next(project.rglob("compare_mini_*.json")).read_text(encoding="utf-8"))


# ------------------------------------------------------------------ 2 x 2 hücreler


def test_fake_compare_writes_a_cell_per_model_and_mode(project, capsys):
    code = run(project, ["fakeA", "fakeB"], llm_kind="fake")
    out = capsys.readouterr().out
    data = report_data(project)

    assert code == 0
    assert list(data["cells"]) == ["fakeA", "fakeB"]
    for model in ("fakeA", "fakeB"):
        assert list(data["cells"][model]) == list(config.COMPARE_MODEL_MODES)
    # Geniş pencere iki modda da sığar; dar pencere ikisinde de taşar — hangi modun hangi
    # pencereye sığdığı sahte koşumda bile okunur (R4-13).
    assert data["cells"]["fakeA"]["full_rules"]["overflows"] == 0
    assert data["cells"]["fakeA"]["rag"]["overflows"] == 0
    assert data["cells"]["fakeB"]["full_rules"]["overflows"] > 0
    assert data["cells"]["fakeB"]["rag"]["overflows"] > 0
    assert list(project.rglob("compare_mini_*.md")), "markdown raporu da yazılmalı"
    assert "Rapor:" in out


# ------------------------------------------------------------------ kapalı uç nokta


def test_a_down_endpoint_is_skipped_with_its_warning(project, capsys):
    code = run(
        project,
        ["fakeA", "fakeB"],
        llm_kind="openai",
        modes=["full_rules"],
        ping=lambda profile: None if profile.name == "fakeA" else "uç nokta kapalı",
    )
    out = capsys.readouterr().out
    data = report_data(project)

    assert code == 0
    assert f"⚠ fakeB: uç nokta yanıt vermiyor ({CLOSED})" in out
    assert list(data["cells"]) == ["fakeA"], "koşmayan modelin hücresi uydurulmaz"
    assert list(data["skipped"]) == ["fakeB"]


def test_every_endpoint_down_writes_no_report(project, capsys):
    code = run(project, ["fakeA", "fakeB"], llm_kind="openai", modes=["full_rules"])
    out = capsys.readouterr().out

    assert code == 3
    assert "⚠ fakeA:" in out and "⚠ fakeB:" in out
    assert not list(project.rglob("compare_mini_*.json")), "koşulmamış bloğun raporu yazılmaz"


# ------------------------------------------------------------------ söz dizimi ve tekrar


def test_modes_without_models_exits_two(capsys):
    code = cli.main(["eval", "--llm", "fake", "--compare", "--modes", "rag"])
    out = capsys.readouterr().out

    assert code == 2
    assert "--modes yalnız --models ile kullanılır." in out


def test_repeat_two_records_the_spread(project, capsys):
    code = run(project, ["fakeA"], llm_kind="fake", modes=["full_rules"], repeat=2)
    capsys.readouterr()
    data = report_data(project)

    assert code == 0
    assert data["repeat"] == 2
    scores = data["cells"]["fakeA"]["full_rules"]["scores"]
    assert {"mean", "min", "max"} <= set(scores)
    assert scores["min"] == scores["max"], "deterministik sahte kayıtta yayılım sıfırdır"
