# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""``eval --compare --models`` ``--repeat``i de doğrular (T161, PLAN R4-13; R3-11 kuralı).

``--repeat 0`` ``range(0)`` yüzünden her hücreyi boş koşup sıfırlarla dolu bir rapor yazıyordu ve
komut 0 çıkıyordu. Artık tekrar geçersizse uç nokta yoklanmaz, hiçbir hücre koşmaz, hiçbir dosya
yazılmaz: ``BAD_REPEAT`` cümlesi basılır ve kod 2 döner. Doğrulama ``compare_models_cmd``nin
içindedir, yani argparse'tan bağımsız çağrıldığında da işler. Profil dosyası ve kümenin çıktıları
testin kendi tmp klasöründe kurulur; gerçek uç noktalara dokunulmaz.
"""

import json
from pathlib import Path

import pytest

from bilgin import config
from bilgin.cli import main as cli

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
CLOSED = "http://127.0.0.1:9/v1"  # discard portu: hiçbir zaman yanıt vermez


def models_file(tmp_path) -> Path:
    """Tek profilli model dosyası; uç nokta kapalı olsa da yoklama stub'ı onu hiç görmez."""
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
                    }
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
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(FIXTURE_ROOT))
    assert cli.build_database(dataset="mini") == 0
    assert cli.build_index("fake", dataset="mini") == 0
    capsys.readouterr()
    return tmp_path


def ping_stub():
    """Yoklandığı her profili not eden sahte yoklama; uç nokta hep açık."""
    calls = []

    def ping(profile):
        calls.append(profile.name)
        return None

    return ping, calls


def run(project, repeat, **kwargs):
    return cli.compare_models_cmd(
        models=["fakeA"],
        dataset="mini",
        models_file=str(models_file(project)),
        repeat=repeat,
        **kwargs,
    )


@pytest.mark.parametrize("repeat", [0, -1])
def test_repeat_below_one_stops_before_anything(project, capsys, repeat):
    ping, calls = ping_stub()
    code = run(project, repeat, llm_kind="openai", modes=["full_rules"], ping=ping)
    out = capsys.readouterr().out

    assert code == 2
    assert cli.BAD_REPEAT in out
    assert calls == [], "tekrar geçersizken hiçbir uç nokta yoklanmaz"
    assert not list(project.rglob("compare_mini_*")), "koşulmayan tekrarın raporu yazılmaz"


def test_repeat_one_still_runs(project, capsys):
    code = run(project, 1, llm_kind="fake", modes=["full_rules"])
    capsys.readouterr()

    assert code == 0
    assert list(project.rglob("compare_mini_*.json")), "geçerli tekrar raporu yazar"
