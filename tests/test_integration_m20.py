# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T257: M20 entegrasyonu — şablondan yeni veri kümesi, elle kurulmuş sahte nesneler olmadan.

Depo gerçek ``UserStore``, kapı gerçek ``create_app``, dünya gerçek ``open_session``: akış
yöneticinin indirdiği boş şablonla başlar, satırları openpyxl ile doldurulur (yani kullanıcının
ekranda yaptığı), önizleme gerçek okuyucudan ve doğrulayıcıdan geçer, uygulama gerçek klasörü
kurar, indeksi gerçek sahte vektörlerle kurar, veritabanı şemanın kendisinden doğar ve uçtaki
soruyu gerçek yürütücü cevaplar. İddia tek cümle: şablonu doldurabilen biri sunucuya yeni bir
veritabanı tanıtır ve o veritabanına soru sorabilir - var olan kümelere ise tek bayt değmez.
"""

import base64
import hashlib
import io
import json
import shutil
import sqlite3
import time
from pathlib import Path
from typing import NamedTuple

import openpyxl
import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from bilgin import config, datasets
from bilgin.app.session import open_session
from bilgin.auth.store import UserStore
from bilgin.cli import main as cli
from bilgin.schema_map import build
from bilgin.schema_map.template import (
    COLUMN_HEADERS,
    DATASET_HEADERS,
    RULE_HEADERS,
    SHEETS,
    TABLE_HEADERS,
)
from bilgin.web.app import create_app
from bilgin.web.authz import NOT_ADMIN
from bilgin.web.map_api import NOT_XLSX, STILL_BROKEN

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "datasets" / "mini"
PAROLA = "Bilgin2026!m20"
ADMIN, USER = "admin", "kullanici"

NEW = "entegre_fatura"  # akışın şablondan kurduğu küme
OLD = "eski_kume"  # ilk yüklemeden önce gerçek kökte hazır duran küme
DEFECT = "kusurlu_kume"  # hatalı yüklemelerin adı; klasörü hiçbir zaman doğmaz
TABLE = "SATIS.FATURA"  # okuyucu adları büyütür; noktalı ad olduğu gibi kalır
DISPLAY = "Satış Faturaları"  # Örneğin GÖRÜNEN AD hücresi
QUESTION = "Fatura sayısı kaç?"  # altın soru değil: sahte model kalıp sorguyu oynatır

DATASET_SHEET, TABLE_SHEET, COLUMN_SHEET, RULE_SHEET, EXAMPLE_SHEET = SHEETS[1:6]

# Kapının kullanıcıya kapattığı yol listesi: haritanın altısı, kümelerin üçü (R6-5, R6-18).
ROUTES = [
    ("get", "/api/schema-map/info", None),
    ("get", "/api/schema-map/template.xlsx", None),
    ("get", "/api/schema-map/sample.xlsx", None),
    ("post", "/api/schema-map/preview", {}),
    ("post", "/api/schema-map/apply", {}),
    ("get", "/api/schema-map/status/abc", None),
    ("get", "/api/datasets", None),
    ("post", "/api/datasets/active", {"name": "mini"}),
    ("get", f"/api/datasets/{NEW}/login-script.sql", None),
]


class World(NamedTuple):
    """Akışın koştuğu tmp dünyası: iki kök, iki hesap, indirilen şablon, yükleme öncesi imzalar."""

    root: Path
    datasets_root: Path
    real_root: Path
    template: bytes
    admin: TestClient
    user: TestClient
    before: dict


# ------------------------------------------------------------------ dünyanın parçaları


def login(app, username) -> TestClient:
    """Giriş yapmış tarayıcı: çerez kavanozu kendine, kapı aynı uygulamaya ait."""
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"username": username, "password": PAROLA})
    assert response.status_code == 200, f"{username} giriş yapamadı: {response.status_code}"
    return client


def copy_dataset(folder: Path, name: str) -> Path:
    """Mini kümesinin kopyası: adı ve çıktı yolları kendi adı, içeriği mini ile aynı."""
    shutil.copytree(FIXTURE, folder)
    meta = json.loads((folder / "dataset.json").read_text(encoding="utf-8"))
    meta["name"] = name
    meta["outputs"] = {
        key: value.replace("mini", name) for key, value in (meta.get("outputs") or {}).items()
    }
    (folder / "dataset.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return folder


def fingerprint(root: Path) -> dict:
    """Ağacın parmak izi: her dosyanın yolu ve baytlarının özeti - tek bayt değişirse imza değişir."""
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def upload(client, data: bytes, filename: str = "sablon.xlsx"):
    return client.post(
        "/api/schema-map/preview",
        json={"filename": filename, "content_b64": base64.b64encode(data).decode()},
    )


def apply(client, preview_id: str):
    return client.post("/api/schema-map/apply", json={"preview_id": preview_id})


def wait_done(client, preview_id: str, timeout: float = 180.0) -> dict:
    """Aşama bir daha değişmeyecek an: indeks işi bitmiş ya da düşmüştür."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/api/schema-map/status/{preview_id}").json()
        if status["phase"] in ("done", "failed"):
            return status
        time.sleep(0.05)
    raise AssertionError(f"iş bitmedi: {preview_id}")


def tables_of(path: Path) -> list[str]:
    """SQLite dosyasındaki tablolar: ad noktalı olsa da diskte tek tablodur."""
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        return [row[0] for row in rows]
    finally:
        conn.close()


# ------------------------------------------------------------------ şablonu kodla doldurmak


def _example_block(sheet, headers: tuple) -> list[tuple]:
    """Örnek sayfasından bir bloğun satırları: başlık satırı aranır, onu izleyen dolu satırlar alınır."""
    width = len(headers)
    rows = list(sheet.iter_rows(values_only=True))
    start = next(index for index, row in enumerate(rows) if row[:width] == headers)
    block = []
    for row in rows[start + 1:]:
        if not any(value not in (None, "") for value in row[:width]):
            break  # bloğun sonu: ilk boş satır, altında öteki blok var
        block.append(row[:width])
    return block


def _write_row(sheet, row: int, values) -> None:
    for index, value in enumerate(values, start=1):
        if value not in (None, ""):
            sheet.cell(row=row, column=index, value=value)


def _write_rows(sheet, rows) -> None:
    for offset, values in enumerate(rows, start=2):
        _write_row(sheet, offset, values)


def fill(template: bytes, name: str, *, keep_reference: bool = False):
    """İndirilen boş şablonu doldurur: Örnek sayfasının blokları gerçek sayfaların satırları olur.

    ASSUMPTION: Örneğin REFERANS'ı şablonda olmayan ``Satis.Cari``'ya gittiği için kopyalanmaz -
    karşılığı olmayan referans hatadır (R6-15); dolu örneği yazan ``filled_example_workbook`` de
    aynı kuralı uygular. ``keep_reference`` o hatayı sınamak için açılır.
    """
    book = openpyxl.load_workbook(io.BytesIO(template))
    example = book[EXAMPLE_SHEET]
    dataset = _example_block(example, DATASET_HEADERS)[0]
    _write_row(
        book[DATASET_SHEET],
        2,
        (name, dataset[1], "sqlite", dataset[3], dataset[4]),
    )
    _write_rows(book[TABLE_SHEET], _example_block(example, TABLE_HEADERS))
    columns = _example_block(example, COLUMN_HEADERS)
    if not keep_reference:
        columns = [row[:7] + ("", row[8]) for row in columns]
    _write_rows(book[COLUMN_SHEET], columns)
    _write_rows(book[RULE_SHEET], _example_block(example, RULE_HEADERS))
    return book


def save(book) -> bytes:
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def _cell(book, sheet: str, row: int, header: str, value) -> None:
    """Başlığıyla hücre bul: kullanıcının Excel'de yaptığı tek hücrelik değişiklik."""
    headers = [item.value for item in book[sheet][1]]
    book[sheet].cell(row=row, column=headers.index(header) + 1).value = value


def _clear_row(book, sheet: str, row: int) -> None:
    for column in range(1, len([item.value for item in book[sheet][1]]) + 1):
        book[sheet].cell(row=row, column=column).value = None


def _copy_row(book, sheet: str, source: int, target: int) -> None:
    for column in range(1, len([item.value for item in book[sheet][1]]) + 1):
        book[sheet].cell(row=target, column=column).value = book[sheet].cell(
            row=source, column=column
        ).value


def _defective(mutate=None, **over):
    """Kusurla doldurulmuş şablonu üreten metot: ``fill``in üstüne tek bir kullanıcı hatası."""

    def make(template: bytes):
        book = fill(template, DEFECT, **over)
        if mutate:
            mutate(book)
        return book

    return make


# Brief'in "her hata uygulamayı engeller" listesi: (şablonu bozan şey, raporda beklenen söz).
DEFECTS = {
    "eksik_zorunlu_hucre": (
        _defective(lambda book: _cell(book, COLUMN_SHEET, 2, "TİP", None)),
        "TİP boş",
    ),
    "sahipsiz_kolon": (
        _defective(lambda book: _clear_row(book, TABLE_SHEET, 2)),
        "Tablolar sayfasında yok",
    ),
    "ikinci_kolon": (
        _defective(lambda book: _copy_row(book, COLUMN_SHEET, 2, 9)),
        "tekrar ediyor",
    ),
    "gecersiz_sinif": (
        _defective(lambda book: _cell(book, COLUMN_SHEET, 7, "KİŞİSEL VERİ", "telefon")),
        "telefon",
    ),
    "bilinmeyen_referans": (_defective(keep_reference=True), "REFERANS"),
    "gecersiz_ad": (
        _defective(lambda book: _cell(book, DATASET_SHEET, 2, "AD", "Entegre-Fatura")),
        "geçersiz",
    ),
    "var_olan_ad": (
        _defective(lambda book: _cell(book, DATASET_SHEET, 2, "AD", OLD)),
        "zaten bir veri kümesi",
    ),
}


# ------------------------------------------------------------------ dünya


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> World:
    """tmp dünyası: üretilmiş mini, gerçek kökte hazır bir küme, tmp uygulama veritabanı.

    ``config.ROOT`` tmp'ye çevrilir ki yeni kümenin ``data/`` ve ``index/`` çıktıları da oraya
    yazılsın; depo kökündeki ``real_datasets/`` hiç açılmaz.
    """
    root = tmp_path_factory.mktemp("m20")
    datasets_root, real_root = root / "datasets", root / "real_datasets"
    shutil.copytree(FIXTURE, datasets_root / "mini")
    copy_dataset(real_root / OLD, OLD)

    mp = MonkeyPatch()
    mp.setattr(config, "ROOT", root)
    mp.setenv("BILGIN_DATASETS_DIR", str(datasets_root))
    mp.setenv("BILGIN_REAL_DATASETS_DIR", str(real_root))
    mp.setenv("BILGIN_APP_DB", str(root / "bilgin.db"))
    mp.setenv("BILGIN_BACKEND", "sqlite")
    mp.setattr(config, "MAP_PREVIEWS_DIR", root / "map_previews")
    mp.setattr(config, "MAP_CHANGES_LOG", root / "logs" / "map_changes.jsonl")
    assert cli.build_database(dataset="mini") == 0
    assert cli.build_index("fake", dataset="mini") == 0

    store = UserStore(root / "bilgin.db")
    store.add_user(ADMIN, PAROLA, "admin")
    store.add_user(USER, PAROLA, "user")
    session = open_session(
        dataset="mini",
        llm="fake",
        audit_path=root / "audit.jsonl",
        ask_log=root / "asks.jsonl",
    )
    app = create_app(
        session, saved_path=root / "bilgin.db", static_dir=root / "static", users=store
    )
    admin, user = login(app, ADMIN), login(app, USER)

    blank = admin.get("/api/schema-map/template.xlsx")
    assert blank.status_code == 200
    assert blank.headers["content-disposition"] == (
        f'attachment; filename="{config.TEMPLATE_FILENAME}"'
    )

    before = {str(path): fingerprint(path) for path in (datasets_root, real_root / OLD)}
    yield World(root, datasets_root, real_root, blank.content, admin, user, before)
    mp.undo()


# ------------------------------------------------------------------ akışın tamamı


def test_a_filled_template_becomes_an_askable_dataset(world):
    preview = upload(world.admin, save(fill(world.template, NEW))).json()

    assert preview["errors"] == []
    assert preview["counts"] == {
        "tables": 1, "columns": 7, "pii": 1, "deny": 1, "references": 0, "rules": 1,
    }
    assert preview["dataset"] == {
        "name": NEW,
        "display_name": DISPLAY,
        "connection": "sqlite",
        "default_schema": "dbo",
        "as_of": "2026-10-01",
    }

    applied = apply(world.admin, preview["preview_id"])
    assert applied.status_code == 200, applied.text
    assert applied.json()["name"] == NEW
    assert wait_done(world.admin, preview["preview_id"]) == {
        "preview_id": preview["preview_id"], "name": NEW, "phase": "done", "message": None,
    }

    # Küme gerçek kökte doğdu; indeksi sahte vektörlerle ve kendi adına kuruldu.
    ds = datasets.load_dataset(NEW)
    assert ds.root == world.real_root / NEW
    assert ds.connection == "sqlite"
    meta = json.loads((ds.index_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["embedder"].startswith("fake") and meta["dataset"] == NEW
    assert [table["name"] for table in ds.schema()["tables"]] == [TABLE]
    assert ds.db_path == world.root / "data" / f"{NEW}.db"
    build.write_sqlite({}, ds.schema(), ds.db_path)
    assert tables_of(ds.db_path) == [TABLE]

    listed = world.admin.get("/api/datasets").json()
    assert [item["name"] for item in listed["datasets"]] == sorted([NEW, OLD, "mini"])
    assert listed["active"] == "mini"
    assert {item["name"]: item for item in listed["datasets"]}[NEW] == {
        "name": NEW,
        "display_name": DISPLAY,
        "connection": "sqlite",
        "root": "real_datasets",
        "path": str(world.real_root / NEW),
        "active": False,
        "index": {"exists": True, "fresh": True, "reason": None},
    }

    switched = world.admin.post("/api/datasets/active", json={"name": NEW}).json()
    assert switched["active"] == NEW
    assert switched["dataset"] == {
        "name": NEW, "display_name": DISPLAY, "connection": "sqlite",
    }
    assert switched["notice"] is None, "sqlite kümesi geçişte bir sonraki adımı gerektirmez"

    answer = world.admin.post("/api/ask", json={"question": QUESTION}).json()
    assert answer["status"] == "answered", answer.get("error")
    assert answer["dataset"] == NEW
    assert TABLE in answer["sql"].upper(), "noktalı ad uçtan uca yüründü"
    assert answer["row_count"] == 1

    # Yükleme öncesi her şey yerinde: yeni klasör eklendi, var olana tek bayt değmedi.
    for path, digest in world.before.items():
        assert fingerprint(Path(path)) == digest, f"{path} yüklendikten sonra değişti"


# ------------------------------------------------------------------ hatalı yüklemeler


@pytest.mark.parametrize("defect", sorted(DEFECTS))
def test_a_defective_template_is_reported_but_never_applied(world, defect):
    make, expected = DEFECTS[defect]

    body = upload(world.admin, save(make(world.template))).json()

    assert body["errors"], f"{defect} rapor edilmedi"
    assert expected in " ".join(item["message"] for item in body["errors"])
    refused = apply(world.admin, body["preview_id"])
    assert (refused.status_code, refused.json()) == (409, {"detail": STILL_BROKEN})
    assert not (world.real_root / DEFECT).exists()
    old = str(world.real_root / OLD)
    assert fingerprint(world.real_root / OLD) == world.before[old], "var olan küme yazılmadı"


def test_a_file_that_is_not_a_workbook_never_reaches_a_preview(world):
    folder = Path(config.MAP_PREVIEWS_DIR)
    before = len(list(folder.glob("*.json"))) if folder.is_dir() else 0

    refused = upload(world.admin, "TABLO,KOLON\nFatura,ID\n".encode(), "sablon.xlsx")

    assert (refused.status_code, refused.json()) == (422, {"detail": NOT_XLSX})
    assert len(list(folder.glob("*.json"))) == before, "bekleyen bir rapor bile yazılmadı"
    assert not (world.real_root / DEFECT).exists()


# ------------------------------------------------------------------ kapı


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_a_user_is_refused_on_every_map_and_datasets_route(world, method, path, body):
    response = world.user.request(method.upper(), path, json=body)

    assert response.status_code == 403, f"{method.upper()} {path} -> {response.status_code}"
    assert response.json() == {"detail": NOT_ADMIN}
