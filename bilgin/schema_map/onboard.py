# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Şablondan veri kümesine: önizlemenin bekletilmesi, uygulanması ve indeks işi (PLAN R6-16).

İki adım, iki ayrı yüz: önizleme diske yazılan tek bir JSON'dır ve hiçbir veri kümesine dokunmaz;
uygulama ise o JSON'u okuyup ``real_datasets/<ad>/`` klasörünü baştan kurar. Aradaki süre
kullanıcının kontrol raporunu okuduğu süredir, o yüzden önizlemenin bir ömrü vardır - süresi geçen
silinir, çünkü raporladığı şablon çoktan değişmiş olabilir.

Uygulama var olan bir klasöre asla yazmaz: klasör ``mkdir(exist_ok=False)`` ile doğar, yarım kalan
bir yazma yalnız kendi klasörünü siler. İndeks işi bu modülde değil arka plandaki bir iş parçacığında
koşar - indeks kurmak bir dakikayı aşabilir, bir HTTP isteği o kadar bekleyemez.
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bilgin import config
from bilgin.engine.login_script import readonly_login_sql
from bilgin.i18n import t
from bilgin.schema_map import rules_edit

# Sözleşme "new dataset folder": klasördeki yedi dosya; adlarını üreten tek yer burası.
LOGIN_SCRIPT_FILE = "readonly_login.sql"
REAL_MODULE = "real.py"
# Sözleşme "new dataset folder": model istemeyen tanıtım sorusunun kalıbı.
FAKE_FALLBACK = "SELECT COUNT(*) AS KAYIT_SAYISI FROM {table}"
# Önizleme kimliği tarayıcıdan gelir; bu biçimin dışındaki bir metin diskte hiçbir yere bakmaz.
PREVIEW_ID_RE = re.compile(r"[0-9a-f]{32}\Z")

# real.py'nin gövdesi: wwi_real'in örneği gibi; üç cümlesi kataloğundur, dili kümenin diliyle yazılır.
_REAL_STUB = '''"""{doc}
"""


def build_db(seed, db_path, sql_path):
    raise SystemExit("{build}")


def generate(seed):
    raise SystemExit("{generate}")


REFERENCES = {{}}
'''


def save_preview(result: dict, username: str, filename: str) -> str:
    """Kontrol raporunu bekletir ve kimliğini verir; başka hiçbir yere yazmaz (R6-16)."""
    preview_id = uuid.uuid4().hex
    _purge(_now())
    folder = Path(config.MAP_PREVIEWS_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    record = {
        "preview_id": preview_id,
        "created_at": _ts(),
        "username": username,
        "filename": filename,
        **result,
    }
    _write_text(_preview_path(preview_id), json.dumps(record, ensure_ascii=False))
    return preview_id


def load_preview(preview_id: str, now: datetime | None = None) -> dict | None:
    """Bekleyen önizleme; yoksa ya da süresi geçmişse None (route bunu 404'e çevirir).

    ``now`` saattir: testler süreyi beklemez, ileri alır. Her çağrı süresi geçenleri de siler.
    """
    if not preview_id or not PREVIEW_ID_RE.match(preview_id):
        return None
    _purge(now or _now())
    path = _preview_path(preview_id)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def apply_preview(preview: dict, username: str, lang: str = "tr") -> Path:
    """Önizlemeyi gerçek bir veri kümesi klasörüne çevirir ve değişimi günlüğe yazar.

    Ad doluysa ``FileExistsError`` yükselir - var olan kümenin tek baytına dokunulmaz. Yazma
    yarıda kalırsa yalnız bu çağrının yarattığı klasör silinir. ``lang`` üretilen ``real.py``nin
    dilidir: klasör bir daha dil değiştirmeyecek, o yüzden küme doğduğu dilde kalır.
    """
    name = preview["dataset"]["name"]
    folder = Path(config.onboard_dir()) / name
    folder.mkdir(parents=True, exist_ok=False)  # HOME/datasets ilk yüklemede daha doğmamıştır
    try:
        schema = _schema_doc(preview)
        _write_json(folder / "dataset.json", _dataset_doc(preview, name))
        _write_json(folder / "schema.json", schema)
        rules_edit.save_rules(preview.get("rules") or [], folder / "rules.json")
        _write_json(folder / "profile.json", {"name": name, "pairs": []})
        _write_text(folder / "golden.jsonl", "")
        _write_text(folder / REAL_MODULE, _real_stub(name, lang))
        _write_text(folder / LOGIN_SCRIPT_FILE, readonly_login_sql(schema, f"bilgin_{name}_ro"))
        _log_change(preview, username, name)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return folder


class IndexJobs:
    """Yeni kümenin indeksi arka planda; aşama bellekte, ekran onu yoklayarak ilerler (R6-16)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}

    def start(self, preview_id: str, name: str, embed: str, suggest=None, lang: str = "tr") -> None:
        """İşi kaydedip döner; indeks kurma iş parçacığında başlar.

        ``suggest`` indeks bittiğinde kümeyi çağıran kancadır (R7-20): yeni doğan kümenin
        başlangıç ekranı boş kalmasın. Kendi iş parçacığında koşan ayrı bir iş çağrılır, yani
        önerinin hatası bu işin aşamasını değiştirmez. ``lang`` işin cümlesinin dilidir: iş
        parçacığının kendi isteği olmadığı için dili onu başlatan yol taşır.
        """
        # ASSUMPTION: `writing` bu kayıttır; iş parçacığı build'e girerken `indexing`e geçer,
        # böylece sözleşmenin dört aşaması iki metotla kurulur.
        self._set(preview_id, name, "writing", None)
        threading.Thread(
            target=self._run, args=(preview_id, name, embed, suggest, lang), daemon=True
        ).start()

    def status(self, preview_id: str) -> dict | None:
        """Sözleşme "apply / status"; hiç başlamamış bir iş için None (route 404 der)."""
        with self._lock:
            job = self._jobs.get(preview_id)
            return dict(job) if job else None

    def _run(self, preview_id: str, name: str, embed: str, suggest=None, lang: str = "tr") -> None:
        # Geç import: şema katmanı, yalnız arka planda ihtiyaç duyduğu CLI'ı döngüye sokmasın.
        from bilgin.cli import main as cli

        self._set(preview_id, name, "indexing", None)
        problem = None
        try:
            code = cli.build_index(embed, dataset=name)
            if code != 0:
                problem = t("onboard.index_failed", lang, name=name, code=code)
        except Exception as exc:  # iş parçacığı buradan öte geçemez; cümle ekrana ulaşmalı
            problem = str(exc) or exc.__class__.__name__
        self._set(preview_id, name, "failed" if problem else "done", problem)
        if problem is None and suggest is not None:
            suggest(name)  # R7-20: öneri küme kurulup indekslendikten sonra istenir, yarım iş kalmasın

    def _set(self, preview_id: str, name: str, phase: str, message: str | None) -> None:
        with self._lock:
            self._jobs[preview_id] = {
                "preview_id": preview_id,
                "name": name,
                "phase": phase,
                "message": message,
            }


def _real_stub(name: str, lang: str) -> str:
    """Klasöre yazılan ``real.py``: gövde sabit, üç cümlesi kataloğun ``lang`` satırları."""
    return _REAL_STUB.format(
        doc=t("onboard.real_stub.doc", lang, name=name),
        build=t("onboard.real_stub.build_db", lang, name=name),
        generate=t("onboard.real_stub.generate", lang, name=name),
    )


def _dataset_doc(preview: dict, name: str) -> dict:
    """Veri kümesinin tanımı (R6-16): çıktı yolları adın, kod gönderimi ``real.py``nin."""
    dataset = preview["dataset"]
    tables = preview["schema"]["tables"]
    return {
        "name": name,
        "display_name": dataset.get("display_name") or name,
        "connection": dataset.get("connection", "mssql"),
        "default_schema": dataset.get("default_schema"),
        "as_of": dataset.get("as_of", ""),
        "seed": config.SEED,
        "files": {
            "schema": "schema.json",
            "rules": "rules.json",
            "profile": "profile.json",
            "golden": "golden.jsonl",
        },
        "builder": f"{REAL_MODULE}:build_db",
        "generator": f"{REAL_MODULE}:generate",
        "references": f"{REAL_MODULE}:REFERENCES",
        "outputs": {
            "db": f"data/{name}.db",
            "mssql_script": f"db/mssql/build_{name}.sql",
            "index_dir": f"index/{name}",
            "eval_out": f"eval_out/{name}",
        },
        "fake_fallback_sql": FAKE_FALLBACK.format(table=tables[0]["name"]) if tables else "",
    }


def _schema_doc(preview: dict) -> dict:
    """Şema belgesi: gerçek bir veritabanının tablosu üretilmiş bir sahte tablo değildir."""
    schema = {"tables": [dict(table) for table in preview["schema"]["tables"]]}
    for table in schema["tables"]:
        table.setdefault("kind", "data")
    return schema


def _log_change(preview: dict, username: str, name: str) -> None:
    """Sözleşme "map change line": kim, ne zaman, hangi küme, kaç tane - satır veri taşımaz."""
    line = {
        "ts": _ts(),
        "username": username,
        "name": name,
        "counts": preview.get("counts") or {},
    }
    path = Path(config.MAP_CHANGES_LOG)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False) + "\n")


def _purge(now: datetime) -> None:
    """Süresi dolmuş önizlemeleri siler: bekleyen bir yükleme diskte birikmesin (R6-16)."""
    folder = Path(config.MAP_PREVIEWS_DIR)
    if not folder.is_dir():
        return
    limit = now - timedelta(minutes=config.MAP_PREVIEW_TTL_MIN)
    for path in folder.glob("*.json"):
        if not PREVIEW_ID_RE.match(path.stem):
            continue  # bizim kimliği taşımayan dosya elimize değmez
        created = _created_at(path)
        if created is None or created <= limit:
            path.unlink(missing_ok=True)


def _created_at(path: Path) -> datetime | None:
    """Önizlemenin doğduğu an; okunamayan dosya önizleme sayılmaz, o yüzden None."""
    try:
        return datetime.fromisoformat(json.loads(path.read_text(encoding="utf-8"))["created_at"])
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _preview_path(preview_id: str) -> Path:
    return Path(config.MAP_PREVIEWS_DIR) / f"{preview_id}.json"


def _write_json(path: Path, payload) -> None:
    """Elle düzenlenecek dosya: Türkçe metin olduğu gibi, iki boşlukla girintili."""
    _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts() -> str:
    return _now().isoformat(timespec="milliseconds")
