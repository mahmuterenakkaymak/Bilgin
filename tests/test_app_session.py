# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T166: Session + open_session (PLAN R5-1).

``open_session`` CLI'nin cümleleriyle doğrular: eksik veritabanı, bilinmeyen küme/profil ve
eksik anahtar hepsi ``SessionError`` (exit 2). ``resolve_mode("auto")`` notu ekrana değil
``notes``a yazar; ``context("rag")`` indeksi olmayan bir oturumda ``MissingIndexError`` yükseltir.
"""

from pathlib import Path

import pytest

from bilgin import config
from bilgin.app.session import SessionError, open_session
from bilgin.cli import main as cli
from bilgin.index.store import MissingIndexError

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(FIXTURE_ROOT))
    return tmp_path


def _build_mini(capsys):
    cli.build_database(dataset="mini")
    capsys.readouterr()


# ------------------------------------------------------------------ open_session: açılış


def test_mini_dataset_with_tmp_paths_opens(project, capsys):
    _build_mini(capsys)
    session = open_session(dataset="mini", llm="fake")
    assert session.dataset.name == "mini"
    assert session.db_path.exists()


def test_missing_db_raises_session_error_code_2(project):
    with pytest.raises(SessionError) as exc:
        open_session(dataset="mini", llm="fake")
    assert exc.value.exit_code == 2
    assert "build-db --dataset mini" in str(exc.value)


def test_unknown_profile_raises_code_2(project):
    with pytest.raises(SessionError) as exc:
        open_session(dataset="mini", model="yok-profil", llm="openai")
    assert exc.value.exit_code == 2


# ------------------------------------------------------------------ resolve_mode: auto + notlar


def test_resolve_mode_auto_with_no_index_returns_full_and_notes(project, monkeypatch, capsys):
    _build_mini(capsys)
    monkeypatch.setattr(config, "AUTO_FULL_MAX_TOKENS", 0)
    session = open_session(dataset="mini", llm="fake")
    notes: list = []
    mode, _ = session.resolve_mode("auto", notes)
    assert mode == "full"
    assert cli.NO_INDEX_NOTE in notes
    assert cli.NO_INDEX_NOTE not in capsys.readouterr().out


# ------------------------------------------------------------------ context: rag indeksi yok


def test_context_rag_with_no_index_raises_missing_index(project, capsys):
    _build_mini(capsys)
    session = open_session(dataset="mini", llm="fake")
    with pytest.raises(MissingIndexError):
        session.context("rag")


# ------------------------------------------------------------------ ping: fake her zaman None


def test_fake_ping_is_none(project, capsys):
    _build_mini(capsys)
    session = open_session(dataset="mini", llm="fake")
    assert session.ping() is None
