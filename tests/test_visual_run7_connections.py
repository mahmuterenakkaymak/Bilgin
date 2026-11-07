# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T343: bağlantı akışları görsel dünyada kendi kümesini ve kendi yoklamasını bulur (PLAN R7-26, R7-28).

``scripts/visual_serve.py`` iki şeyi daha kurar: bekçiyle guard'ın sunucu yerine okuduğu
``data/visual/db_probe.json``, ve haritadan doğmuş, SQL Server diyen ``vitrin_kapali``. Birincisi
olmadan başlığın noktası renklenmez - SQLite kümesinin yoklanacak bağlantısı yoktur - ikincisi
olmadan bağlantıları ekranının düzenlenecek tek satırı olmaz ve "Bu kümeye geç" düğmesi kapalı
kalır. Üçü de ``.hybrid/visual.json``daki üç sayfaya yazıldığı için ölçülen şey hem diskteki hem
akıştaki karşılığıdır.

ASSUMPTION: iki nokta sayfası kümesini kendisi seçer - koşu ``wwi``de açılıyor ve ondan önceki
sayfa orada bırakıyor, o dünyada kullanıcının gördüğü nokta "bağlantı yok" olurdu.
"""

import contextlib
import json
import re
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from nl2sql import config, datasets
from nl2sql.index.store import META_FILE
from nl2sql.schema_map import template
from scripts import visual_serve

VISUAL_PATH = config.ROOT / ".hybrid" / "visual.json"
SRC_DIR = config.ROOT / "web" / "src"

# Üç sayfa R7-27'nin iki yüzünü koşar: yöneticinin bağlantı formu ve iki renkli başlık noktası.
PAGES = ("admin-connections", "db-dot-user-ok", "db-dot-user-down")
DOT_PAGES = ("db-dot-user-ok", "db-dot-user-down")

ID_PART = re.compile(r"#([\w-]+)")
ATTR_PART = re.compile(r"\[\s*([\w-]+)")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Kum havuzu tmp'nin içine taşınır: test ne ``data/`` ne ``real_datasets/`` dokunur.

    ``prepare`` klasörleri ``config``den okuduğu için iki ortam değişkeni de burada kurulur;
    monkeypatch bunları test sonunda geri verir, yani sızıntı başka teste taşınmaz.
    """
    root = tmp_path / "visual"
    monkeypatch.setattr(visual_serve, "VISUAL_DIR", root)
    monkeypatch.setattr(config, "ROOT", tmp_path)  # küme sözleşmesinin data/ ve index/ yolları
    monkeypatch.setenv("NL2SQL_APP_DB", str(root / "bilgin.db"))
    monkeypatch.setenv("NL2SQL_REAL_DATASETS_DIR", str(root / "real_datasets"))
    return root


def page(name: str) -> dict:
    doc = json.loads(VISUAL_PATH.read_text(encoding="utf-8"))
    return next(item for item in doc["pages"] if item["name"] == name)


def clicks_of(name: str) -> list[str]:
    return [step["click"] for step in page(name)["steps"] if isinstance(step, dict) and "click" in step]


def selectors_of(name: str) -> list[str]:
    found = []
    for step in page(name)["steps"]:
        if isinstance(step, dict):
            if "click" in step:
                found.append(step["click"])
            if "fill" in step:
                found.append(step["fill"][0])
    return found


def source_text() -> str:
    """Arayüzün kaynak dosyaları: testler değil, bileşenlerin kendileri."""
    files = [
        path
        for path in sorted(SRC_DIR.rglob("*"))
        if path.suffix in (".js", ".jsx") and ".test." not in path.name
    ]
    return "\n".join(path.read_text(encoding="utf-8") for path in files)


# ------------------------------------------------------------------ hazırlığın kurdukları


def test_prepare_leaves_the_probe_the_dots_read(sandbox):
    probe = visual_serve.prepare()

    assert probe == sandbox / "db_probe.json"
    assert json.loads(probe.read_text(encoding="utf-8")) == {
        "status": {"synthetic_erp": "ok", "vitrin_kapali": "down"},
        "guard": {"ro.local": "readonly", "sa.local": "sysadmin"},
    }


def test_the_probe_is_never_written_outside_the_sandbox(sandbox):
    outside = sandbox.parent / "db_probe.json"

    with pytest.raises(visual_serve.VisualError):
        visual_serve.write_probe(outside)

    assert not outside.exists(), "reddedilen yol kurulmuş"


def test_the_vitrine_is_a_dataset_the_flow_can_switch_to(sandbox):
    """Küme haritanın kendi yolundan doğar; geçişin iki koşulu da yoklama dosyasında değildir."""
    visual_serve.prepare()

    ds = datasets.load_dataset(visual_serve.VITRIN_DATASET)
    with contextlib.closing(sqlite3.connect(ds.db_path)) as conn:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]

    assert ds.root == sandbox / "real_datasets" / visual_serve.VITRIN_DATASET
    assert ds.connection == "mssql", "bağlantıları ekranı yalnız SQL Server kümelerini listeler"
    assert [name.upper() for name in tables] == [template.EXAMPLE_TABLE.upper()]
    assert ds.db_path.is_file(), "geçişin sorgulayacağı veritabanı yok"
    assert (ds.index_dir / META_FILE).is_file(), "düğme yalnız indeksi olan kümeye açık"


def test_serve_is_started_with_the_probe_file(sandbox, monkeypatch):
    """Bekçi dosyayı ``serve``a giden bayraktan görür; hazırlık onu kendi yazdığı yoldan taşır."""
    probe = visual_serve.write_probe()
    commands = []

    def fake_call(command, **kwargs):
        commands.append(command)
        return 0

    monkeypatch.setattr(visual_serve, "prepare", lambda: probe)
    monkeypatch.setattr(visual_serve, "subprocess", SimpleNamespace(call=fake_call))

    assert visual_serve.main(["--port", "8777"]) == 0

    serve = commands[0]
    assert serve[:4] == [sys.executable, "-m", "nl2sql", "serve"]
    assert serve[serve.index("--db-probe-file") + 1] == str(probe)


# ------------------------------------------------------------------ akışın üç sayfası


@pytest.mark.parametrize("name", PAGES)
def test_each_page_logs_in_to_the_sandbox(name):
    steps = page(name)["steps"]
    typed = [
        step["fill"][1]
        for step in steps
        if isinstance(step, dict) and step.get("fill", [None])[0] == "#login-password"
    ]

    assert visual_serve.VISUAL_PASSWORD in typed, f"{name} doğru parolayı yazmıyor"
    assert {"click": "#login-submit"} in steps, f"{name} giriş düğmesine basmıyor"


@pytest.mark.parametrize("name", DOT_PAGES)
def test_a_dot_page_picks_a_dataset_that_has_a_connection(name):
    """Nokta SQLite kümesinde renklenmez; iki sayfa da ``synthetic_erp``yi kendisi seçer."""
    assert "button[data-dataset-activate='synthetic_erp']" in clicks_of(name)


def test_the_down_page_walks_the_vitrine_dataset_it_is_named_for():
    clicks = clicks_of("db-dot-user-down")
    vitrine = f"button[data-dataset-activate='{visual_serve.VITRIN_DATASET}']"

    assert vitrine in clicks, "akış düşmüş kümeye geçmiyor"
    assert clicks.index(vitrine) < clicks.index("button[data-dataset-activate='synthetic_erp']"), (
        "geri dönüş geçişin önünde kalıyor"
    )


@pytest.mark.parametrize("name", PAGES)
def test_every_selector_of_the_three_pages_is_in_the_ui_source(name):
    """Bir id ekrandan kalkarsa akış boşluğa tıklar ve yanlış kareyi "doğru" diye gösterir."""
    text = source_text()

    for selector in selectors_of(name):
        names = ID_PART.findall(selector) + ATTR_PART.findall(selector)
        assert names, f"{name}: {selector} denetlenecek bir ad taşımıyor"
        missing = [part for part in names if part not in text]
        assert not missing, f"{name} akışındaki {selector!r} kaynakta yok: {missing}"
