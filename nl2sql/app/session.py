# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

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
from nl2sql.agent import fake
from nl2sql.agent.llm import (
    ModelProfile,
    ProfileError,
    get_profile,
    key_missing_reason,
    ping as llm_ping,
)
from nl2sql.engine.connections import ConnectionStore
from nl2sql.engine.connections import resolve as resolve_connection
from nl2sql.engine.executor import LocalExecutor
from nl2sql.index.store import dataset_arg
from nl2sql.schema_map import doc
from nl2sql.schema_map.rules import load_rules

# CLI'nin cümlesi: SessionError bunu taşıyor, yani web ile CLI aynı hatayı söylüyor.
NO_DB = "Veritabanı yok: {path}\nÖnce `python -m nl2sql build-db{ds}` çalıştırın."


class SessionError(Exception):
    """Oturum kurulamadı; mesaj CLI'nin cümlesi, exit_code CLI'nin exit kodu (PLAN R5-1).

    ``key`` ve ``params`` aynı hatanın kataloğun anahtarıyla alanlarıdır (R8-5): web yolu anahtarı
    olan bir reddi isteğin dilinde katalogdan okur; anahtarı olmayan istisna CLI'nin cümlesiyle
    konuşmaya devam eder.
    """

    def __init__(
        self,
        message: str,
        exit_code: int,
        key: str | None = None,
        params: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.key = key
        self.params = params or {}


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
    # R6-18: küme geçişi modeli kendi dosyasından yeniden okur, yani sunucuya söylenen dosya unutulmaz.
    models_file: str | Path | None = None

    def agent_llm(self, mode: str):
        """Modun istemcisi: client_factory verildiyse o, değilse CLI'nin make_client'ı."""
        if self.client_factory is not None:
            return self.client_factory(mode)
        from nl2sql.cli import main as cli

        return cli.make_client(self.llm_kind, mode, self.dataset, self.profile)

    def narrator(self):
        """Anlatıcının istemcisi: fake kendi cümlesini kurar, açık uç ajanınkiyle aynı uca gider."""
        if self.llm_kind == "fake":
            return fake.narration_client()
        # ASSUMPTION: anlatıcı araçsız düz metin istediği için mod istemcinin seçiminde söz sahibi
        # değil; ajanınkiyle aynı kurulum "full" ile istenir.
        return self.agent_llm("full")

    def context(self, mode: str, clarify: bool = False, answer_lang: str = "tr"):
        """Modun bağlamı (ToolContext); clarify açıkken ajan ask_clarification da görebilir (R5-10),
        answer_lang cevabın dilini taşır (R8-9)."""
        from nl2sql.cli import main as cli

        return cli._context(
            mode, self.executor, self.schema, self.rules, self.index_dir, self.dataset,
            clarify=clarify, answer_lang=answer_lang,
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
    connections: ConnectionStore | None = None,
    active: bool = True,
) -> Session:
    """CLI'nin cümleleriyle doğrulanan bir Session kurar; hata SessionError(exit_code=2).

    ``connections`` bağlantı deposudur (R7-23): küme SQL Server ilan etmiş ve kendi dizesi
    çözülüyorsa yürütücü o sunucuya kurulur, ``active`` ise açılan kümenin etkin küme olup
    olmadığıdır - genel ortam değişkeni yalnız ona aittir. Başka her durumda Run 6'ın hâli sürer.
    """
    ds = _load_dataset(dataset)
    profile = _load_profile(model, models_file)
    if llm == "openai" and profile is not None:
        reason = key_missing_reason(profile.api_key_env)
        if reason:
            raise SessionError(
                reason,
                2,
                key="session.key_missing",
                params={"env": profile.api_key_env},
            )
    backend, conn_str = _connection(ds, connections, active)
    resolved_db = _or(db_path, ds.db_path if ds else None, config.DB_PATH)
    # Bağlantısı çözülmüş bir SQL Server kümesi ölçümünü sunucudan alır: klasördeki SQLite
    # dosyası o oturumun koşulu değildir.
    if conn_str is None and _db_missing(resolved_db):
        build_arg = dataset_arg(ds.name if ds else None)
        raise SessionError(
            NO_DB.format(path=resolved_db, ds=build_arg),
            2,
            key="session.no_db",
            params={"path": resolved_db, "ds": build_arg},
        )
    resolved_index = _or(index_dir, ds.index_dir if ds else None, config.INDEX_DIR)
    schema = ds.schema() if ds else doc.load_schema()
    rules = ds.rules() if ds else load_rules()
    executor = LocalExecutor(
        backend=backend,
        db_path=resolved_db,
        allowlist=doc.allowlist(schema),
        audit_path=audit_path,
        pii_schema=schema,
        conn_str=conn_str,
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
        models_file=models_file,
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


def _connection(
    ds, connections: ConnectionStore | None, active: bool
) -> tuple[str | None, str | None]:
    """R7-23: yürütücünün yedeği ve bağlantı dizesi; dize yoksa ``(None, None)``, yani Run 6.

    ``env`` kaynağı bilinçli olarak Run 6'a bırakılır: genel ``NL2SQL_MSSQL_CONN``u ``_mssql.run``
    kendisi okuyor, yani yürütücünün ona ihtiyacı yoktur; yedeği de config söylüyordur.
    """
    if ds is None or connections is None or ds.connection != "mssql":
        return None, None
    where = resolve_connection(ds.name, connections, ds.name if active else None)
    if where["source"] not in ("env_dataset", "stored"):
        return None, None
    return "mssql", where["conn_str"]


def _db_missing(db_path: str | Path) -> bool:
    return config.backend() == "sqlite" and not Path(db_path).exists()


def _or(value, *fallbacks):
    for candidate in (value, *fallbacks):
        if candidate is not None:
            return candidate
    return None
