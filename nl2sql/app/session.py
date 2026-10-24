"""Run 5 web oturumu: CLI'nin parçalarını bir nesnede toplayan katman (PLAN R5-1).

``Session`` bir ``ask`` ya da ``serve`` koşumunun ihtiyaç duyduğu her şeyi tek yerde taşır.
``open_session`` aynı kurulumu CLI'nin kendi cümleleriyle doğrular; hata ``SessionError``dır
ve exit kodu CLI'nin exit koduyla aynıdır (2).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from nl2sql import config, datasets
from nl2sql.agent.llm import (
    ModelProfile,
    ProfileError,
    get_profile,
    key_missing_reason,
    ping as llm_ping,
)
from nl2sql.engine.executor import LocalExecutor
from nl2sql.index.store import dataset_arg
from nl2sql.schema_map import doc
from nl2sql.schema_map.rules import load_rules

# CLI'nin cümlesi: SessionError bunu taşıyor, yani web ile CLI aynı hatayı söylüyor.
NO_DB = "Veritabanı yok: {path}\nÖnce `python -m nl2sql build-db{ds}` çalıştırın."


class SessionError(Exception):
    """Oturum kurulamadı; mesaj CLI'nin cümlesi, exit_code CLI'nin exit kodu (PLAN R5-1)."""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass
class Session:
    """Bir web ya da CLI koşumunun dünyası: şema, kurallar, executor, profil, yollar."""

    dataset: datasets.Dataset | None
    schema: dict
    rules: list
    executor: LocalExecutor
    profile: ModelProfile | None
    budget: int | None
    llm_kind: str
    index_dir: Path
    db_path: Path
    audit_path: Path
    ask_log: Path
    client_factory: Callable | None = None

    def agent_llm(self, mode: str):
        """Modun istemcisi: client_factory verildiyse o, değilse CLI'nin make_client'ı."""
        if self.client_factory is not None:
            return self.client_factory(mode)
        from nl2sql.cli import main as cli

        return cli.make_client(self.llm_kind, mode, self.dataset, self.profile)

    def context(self, mode: str, clarify: bool = False):
        """Modun bağlamı (ToolContext)."""
        # ASSUMPTION: clarify T184 ToolContext'a alan ekleyene dek yok sayılır.
        from nl2sql.cli import main as cli

        return cli._context(
            mode, self.executor, self.schema, self.rules, self.index_dir, self.dataset
        )

    def resolve_mode(self, mode: str, notes: list) -> tuple[str, int | None]:
        """auto'yu çözer; notlar notes'a eklenir, ekrana hiçbir şey basılmaz."""
        if mode != "auto":
            return mode, None
        from nl2sql.cli import main as cli

        return cli.resolve_auto(
            self.schema,
            self.rules,
            self.index_dir,
            self.dataset.as_of if self.dataset else config.AS_OF,
            self.dataset.name if self.dataset else None,
            max_tokens=cli._auto_limit(self.profile),
            notify=notes.append,
        )

    def reload_rules(self) -> None:
        """Kuralları diskten yeniden okur."""
        self.rules = self.dataset.rules() if self.dataset else load_rules()

    def ping(self) -> str | None:
        """Uç nokta sağ mı: fake her zaman None; openai profil ya da config ile yoklar."""
        if self.llm_kind == "fake":
            return None
        if self.profile is not None:
            return llm_ping(self.profile)
        settings = config.llm_settings()
        return llm_ping(
            ModelProfile(name=settings.model, base_url=settings.base_url, model=settings.model)
        )


def open_session(
    dataset: str | None = None,
    model: str | None = None,
    llm: str = "openai",
    models_file: str | Path | None = None,
    db_path: str | Path | None = None,
    index_dir: str | Path | None = None,
    audit_path: str | Path = config.AUDIT_LOG,
    ask_log: str | Path = config.ASK_LOG,
    client_factory: Callable | None = None,
) -> Session:
    """CLI'nin cümleleriyle doğrulanan bir Session kurar; hata SessionError(exit_code=2)."""
    ds = _load_dataset(dataset)
    profile = _load_profile(model, models_file)
    if llm == "openai" and profile is not None:
        reason = key_missing_reason(profile.api_key_env)
        if reason:
            raise SessionError(reason, 2)
    resolved_db = _or(db_path, ds.db_path if ds else None, config.DB_PATH)
    if _db_missing(resolved_db):
        raise SessionError(
            NO_DB.format(path=resolved_db, ds=dataset_arg(ds.name if ds else None)), 2
        )
    resolved_index = _or(index_dir, ds.index_dir if ds else None, config.INDEX_DIR)
    schema = ds.schema() if ds else doc.load_schema()
    rules = ds.rules() if ds else load_rules()
    executor = LocalExecutor(
        db_path=resolved_db,
        allowlist=doc.allowlist(schema),
        audit_path=audit_path,
        pii_schema=schema,
    )
    return Session(
        dataset=ds,
        schema=schema,
        rules=rules,
        executor=executor,
        profile=profile,
        budget=profile.prompt_limit if profile else None,
        llm_kind=llm,
        index_dir=Path(resolved_index),
        db_path=Path(resolved_db),
        audit_path=Path(audit_path),
        ask_log=Path(ask_log),
        client_factory=client_factory,
    )


def _load_dataset(name: str | None) -> datasets.Dataset | None:
    if not name:
        return None
    try:
        return datasets.load_dataset(name)
    except datasets.DatasetError as exc:
        raise SessionError(str(exc), 2) from exc


def _load_profile(name: str | None, path: str | Path | None) -> ModelProfile | None:
    if not name:
        return None
    try:
        return get_profile(name, path)
    except ProfileError as exc:
        raise SessionError(str(exc), 2) from exc


def _db_missing(db_path: str | Path) -> bool:
    return config.backend() == "sqlite" and not Path(db_path).exists()


def _or(value, *fallbacks):
    for candidate in (value, *fallbacks):
        if candidate is not None:
            return candidate
    return None
