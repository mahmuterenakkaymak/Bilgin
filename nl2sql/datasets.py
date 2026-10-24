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

from nl2sql import config
from nl2sql.schema_map import doc
from nl2sql.schema_map.rules import load_rules

# dataset.json'un sözleşme varsayılanları (Contracts, Run 4 additions).
FILE_DEFAULTS = {
    "schema": "schema.json",
    "rules": "rules.json",
    "profile": "profile.json",
    "golden": "golden.jsonl",
    "traps": None,
}
REQUIRED_KEYS = ("name", "as_of", "builder", "generator", "references")


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
    traps_path: Path | None
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

    def golden(self) -> list[dict]:
        """The golden questions, so the Run 2 list fields get their empty defaults."""
        # Lazy: the loader stays light - the runner pulls in the agent loop and the executor.
        from nl2sql.eval import runner

        return runner.load_golden(self.golden_path)


def list_datasets(root: str | Path | None = None) -> list[str]:
    """Sorted names of the folders under ``root`` that hold a ``dataset.json``."""
    base = Path(config.datasets_dir() if root is None else root)
    return sorted(path.parent.name for path in base.glob("*/dataset.json"))


def load_dataset(name: str, root: str | Path | None = None) -> Dataset:
    """The dataset folder ``name`` under ``root`` (default ``config.datasets_dir()``)."""
    base = Path(config.datasets_dir() if root is None else root)
    folder = base / name
    path = folder / "dataset.json"
    if not path.is_file():
        known = ", ".join(list_datasets(base))
        raise DatasetError(f"Bilinmeyen veri kümesi: {name} (bilinenler: {known})")
    raw = json.loads(path.read_text(encoding="utf-8"))
    for key in REQUIRED_KEYS:
        if not raw.get(key):
            raise DatasetError(f"Veri kümesi tanımı geçersiz: '{key}' yok ({path})")

    name = raw["name"]
    files = {**FILE_DEFAULTS, **(raw.get("files") or {})}
    outputs = raw.get("outputs") or {}
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
        traps_path=folder / files["traps"] if files["traps"] else None,
        db_path=config.ROOT / outputs.get("db", f"data/{name}.db"),
        mssql_script=config.ROOT / outputs.get("mssql_script", f"db/mssql/build_{name}.sql"),
        index_dir=config.ROOT / outputs.get("index_dir", f"index/{name}"),
        eval_out=config.ROOT / outputs.get("eval_out", f"eval_out/{name}"),
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
        f"nl2sql_dataset_{name}_{Path(target).stem}", root / target
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
