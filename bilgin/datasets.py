# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Veri kümeleri: bir klasör + ``dataset.json`` -> yollar, tohum, builder, generator, referans.

Bir veri kümesi şemasını, kurallarını, profilini, golden sorularını, test veritabanını kuran
kod ve cevapları bağımsız hesaplayan Python referansını tek klasörde taşır (PLAN R4-1).
``load_dataset`` o klasörü okuyup ``Dataset``'a çevirir; ``builder``/``generator``/``references``
kod gönderimleri **ilk kullanımda** çözülür, böylece bir kümeyi listelemek ya da yollarını
okumak için içindeki Python'u import etmeye gerek kalmaz.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bilgin import config
from bilgin.schema_map import doc
from bilgin.schema_map.rules import load_rules

# dataset.json'un sözleşme varsayılanları (Contracts, Run 4 additions).
FILE_DEFAULTS = {
    "schema": "schema.json",
    "rules": "rules.json",
    "profile": "profile.json",
    "golden": "golden.jsonl",
    "golden_en": None,
    "traps": None,
    "ambiguous": None,
    "followups": None,
    "followups_en": None,
    "ready_questions": None,
}

REQUIRED_KEYS = ("name", "as_of", "builder", "generator", "references")

# Zincir satırlarının liste alanları (PLAN R7-13); dosyada yazılmadığında boş kabul edilir.
FOLLOWUP_LIST_FIELDS = ("uses_turns", "tags")

# ``all_datasets``'in "root" etiketleri; ``_roots`` sırasıyla birebir eşleşir (PLAN R6-11, R8-20).
ROOT_LABELS = ("datasets", "real_datasets", "home_datasets")


class DatasetError(Exception):
    """Klasör veri kümesi değil ya da ``dataset.json`` eksik."""


@dataclass(frozen=True)
class Dataset:
    """One dataset folder: every path it owns plus the code references behind it."""

    name: str
    display_name: str
    dialect: str
    connection: str
    default_schema: str | None
    as_of: str
    seed: int
    root: Path
    schema_path: Path
    rules_path: Path
    profile_path: Path
    golden_path: Path
    golden_en_path: Path | None
    traps_path: Path | None
    ambiguous_path: Path | None
    followups_path: Path | None
    followups_en_path: Path | None
    ready_questions_path: Path | None
    db_path: Path
    mssql_script: Path
    index_dir: Path
    eval_out: Path
    fake_fallback_sql: str
    builder_ref: str
    generator_ref: str
    references_ref: str

    def build_db(
        self,
        seed: int | None = None,
        db_path: str | Path | None = None,
        sql_path: str | Path | None = None,
    ) -> str:
        """Build this dataset's SQLite DB and T-SQL script; returns the SQLite checksum."""
        builder = _resolve(self.name, self.builder_ref, self.root)
        return builder(
            self.seed if seed is None else seed,
            self.db_path if db_path is None else db_path,
            self.mssql_script if sql_path is None else sql_path,
        )

    def generate(self, seed: int | None = None) -> dict[str, list[dict]]:
        """The dataset's in-memory rows: ``dict[table, list[dict]]`` for one seed."""
        generator = _resolve(self.name, self.generator_ref, self.root)
        return generator(self.seed if seed is None else seed)

    def references(self) -> dict:
        """``qid -> callable(rows)` computing each golden answer in Python."""
        return _resolve(self.name, self.references_ref, self.root)

    def schema(self) -> dict:
        """The schema doc of this dataset, with the contract defaults applied."""
        return doc.load_schema(self.schema_path)

    def rules(self) -> list[dict]:
        """The business rules of this dataset, with the contract defaults applied."""
        return load_rules(self.rules_path)

    def golden(self, lang: str = "tr") -> list[dict]:
        """The golden questions, so the Run 2 list fields get their empty defaults.

        ``lang="en"`` reads the English set (PLAN R8-10); a dataset that declares no
        ``files.golden_en`` answers an English question with the Turkish one.
        """
        # Lazy: the loader stays light - the runner pulls in the agent loop and the executor.
        from bilgin.eval import runner

        declared = lang == "en" and self.golden_en_path is not None
        return runner.load_golden(self.golden_en_path if declared else self.golden_path)

    def ambiguous(self) -> list[dict]:
        """Belirsiz sorular (PLAN R5-12); kümenin böyle bir dosyası yoksa boş, yani soru sorulmaz.

        Satırların doğruluğu ölçümün işidir; burada yalnız okunur, boş satırlar atlanır.
        """
        if self.ambiguous_path is None or not self.ambiguous_path.is_file():
            return []
        return [
            json.loads(line)
            for line in self.ambiguous_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def followups(self, lang: str = "tr") -> list[dict]:
        """Ardışık soru zincirleri (PLAN R7-13); kümenin böyle bir dosyası yoksa boş.

        Zincirlerin doğruluğu ölçümün işidir; burada yalnız okunur, boş satırlar atlanır ve
        sözleşmenin liste alanları boş varsayılanlarını alır. ``lang="en"`` kümenin İngilizce
        zincirlerini okur (R8-10); ``files.followups_en`` yoksa zincirler Türkçe halidir.
        """
        declared = lang == "en" and self.followups_en_path is not None
        path = self.followups_en_path if declared else self.followups_path
        if path is None or not path.is_file():
            return []
        chains = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            chain = json.loads(line)
            chain.setdefault("tags", [])
            for turn in chain["turns"]:
                for name in FOLLOWUP_LIST_FIELDS:
                    turn.setdefault(name, [])
            chains.append(chain)
        return chains

    def ready_questions(self) -> list[dict]:
        """Tohum hazır sorular (PLAN R7-19); kümenin böyle bir dosyası yoksa boş.

        Satırların doğruluğu tohumun kendi testidir (``tests/test_ready_seed.py``); burada yalnız
        okunur ve sözleşmenin ``position`` alanı boş varsayılanını alır.
        """
        if self.ready_questions_path is None or not self.ready_questions_path.is_file():
            return []
        rows = json.loads(self.ready_questions_path.read_text(encoding="utf-8"))
        for row in rows:
            row.setdefault("position", 0)
        return rows


def list_datasets(root: str | Path | None = None) -> list[str]:
    """Sorted names of the folders under ``root`` that hold a ``dataset.json``."""
    base = Path(config.datasets_dir() if root is None else root)
    return sorted(path.parent.name for path in base.glob("*/dataset.json"))


def _roots() -> list[Path]:
    """Arama sırası (PLAN R6-11, R8-20): üretilen kümelerin kökü, sonra ekrandan yüklenenlerin.

    Üçüncü kök yalnız ``BILGIN_HOME`` kuruluyken gelir: yüklemenin yazdığı ``HOME/datasets``.
    O kurulmayken ``onboard_dir`` zaten ikinci köktür, o yüzden liste uzamaz.
    """
    roots = [Path(config.datasets_dir()), Path(config.real_datasets_dir())]
    onboarded = config.onboard_dir()
    if onboarded not in roots:
        roots.append(onboarded)
    return roots


def all_datasets() -> list[dict]:
    """Köklerdeki veri kümeleri ad sırasıyla; ``root`` kümenin hangi kökten geldiğini söy.

    Aynı ad iki kökte de varsa ilk kök kazanır; ``path`` klasörün dizgi halidir, böylece
    öğe olduğu gibi JSON'a yazılabilir.
    """
    found: dict[str, dict] = {}
    for label, base in zip(ROOT_LABELS, _roots()):
        for name in list_datasets(base):
            if name in found:
                continue
            try:
                dataset = load_dataset(name, root=base)
            except (DatasetError, OSError, json.JSONDecodeError):
                # Yarıda kesilmiş bir apply (R6-16) ya da elle düzenlenmiş bir dataset.json tek
                # başına listeyi düşürmez: klasör atlanır, adı ``name_taken`` için yine dolu sayılır.
                continue
            found[name] = {
                "name": dataset.name,
                "display_name": dataset.display_name,
                "connection": dataset.connection,
                "root": label,
                "path": str(dataset.root),
            }
    return [found[name] for name in sorted(found)]


def name_taken(name: str) -> bool:
    """True when a folder of that name exists in either root, with or without a ``dataset.json``."""
    return any((base / name).is_dir() for base in _roots())


def load_dataset(name: str, root: str | Path | None = None) -> Dataset:
    """The dataset folder ``name``: under ``root``, else ``datasets_dir()`` then ``real_datasets_dir()``."""
    bases = [Path(root)] if root is not None else _roots()
    for base in bases:
        if (base / name / "dataset.json").is_file():
            return _read(base, name)
    known = sorted({n for base in bases for n in list_datasets(base)})
    raise DatasetError(f"Bilinmeyen veri kümesi: {name} (bilinenler: {', '.join(known)})")


def _read(base: Path, name: str) -> Dataset:
    """``base/name``'in ``dataset.json``'unu okuyup ``Dataset``'a çevirir (var olduğu biliniyor)."""
    folder = base / name
    path = folder / "dataset.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        # Hata DatasetError olarak kalır ki yükleyen herkes (CLI, oturum, web) aynı cümleyi söylesin.
        raise DatasetError(f"Veri kümesi tanımı okunamıyor: {path}") from exc
    for key in REQUIRED_KEYS:
        if not raw.get(key):
            raise DatasetError(f"Veri kümesi tanımı geçersiz: '{key}' yok ({path})")

    name = raw["name"]
    files = {**FILE_DEFAULTS, **(raw.get("files") or {})}
    outputs = raw.get("outputs") or {}
    # Üretilen dosyalar ikiye ayrılır (PLAN R8-20): veritabanı ve T-SQL betiği kodla birlikte
    # depoda durur, indeks ile ölçüm çıktısı koşan kurulumun HOME'una yazılır.
    home = config.home_dir()
    golden_path = folder / files["golden"]
    return Dataset(
        name=name,
        display_name=raw.get("display_name") or name,
        dialect=raw.get("dialect", "tsql"),
        connection=raw.get("connection", "sqlite"),
        default_schema=raw.get("default_schema"),
        as_of=raw["as_of"],
        seed=raw.get("seed", config.SEED),
        root=folder,
        schema_path=folder / files["schema"],
        rules_path=folder / files["rules"],
        profile_path=folder / files["profile"],
        golden_path=golden_path,
        golden_en_path=folder / files["golden_en"] if files["golden_en"] else None,
        traps_path=folder / files["traps"] if files["traps"] else None,
        ambiguous_path=folder / files["ambiguous"] if files["ambiguous"] else None,
        followups_path=folder / files["followups"] if files["followups"] else None,
        followups_en_path=folder / files["followups_en"] if files["followups_en"] else None,
        ready_questions_path=folder / files["ready_questions"] if files["ready_questions"] else None,
        db_path=config.ROOT / outputs.get("db", f"data/{name}.db"),
        mssql_script=config.ROOT / outputs.get("mssql_script", f"db/mssql/build_{name}.sql"),
        index_dir=home / outputs.get("index_dir", f"index/{name}"),
        eval_out=home / outputs.get("eval_out", f"eval_out/{name}"),
        fake_fallback_sql=raw.get("fake_fallback_sql") or _first_golden_sql(golden_path),
        builder_ref=raw["builder"],
        generator_ref=raw["generator"],
        references_ref=raw["references"],
    )


def _first_golden_sql(path: Path) -> str:
    """The first golden line's SQL - the fake LLM's fallback when dataset.json names none."""
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            return json.loads(line).get("sql", "")
    return ""


def _resolve(name: str, ref: str, root: Path) -> Any:
    """``module.path:attr`` imported, ``file.py:attr`` loaded from the dataset folder."""
    target, _, attribute = ref.partition(":")
    if target.endswith(".py") or "/" in target or "\\" in target:
        return getattr(_load_file(name, target, root), attribute)
    return getattr(importlib.import_module(target), attribute)


def _load_file(name: str, target: str, root: Path):
    """A dataset's own module, named so it can never shadow an installed package."""
    spec = importlib.util.spec_from_file_location(
        f"bilgin_dataset_{name}_{Path(target).stem}", root / target
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
