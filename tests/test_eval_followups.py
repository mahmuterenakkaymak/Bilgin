# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T305: ardışık soru zincirlerinin ölçümü gerçek kapıdan koşar (PLAN R7-14).

``run_followups`` zinciri ``ask_payload``ın içinden geçirir; her tur için runner'ın golden SQL
karşısındaki kararını, zincirin kararını ve bağlam doğruluğunu sayar. Sentetik ERP + sahte istemci
her turu kendi golden SQL'iyle cevapladığı için üç doğruluk da 1.0; ikinci turu birincinin SQL'iyle
cevaplayan bir sahte o turu ve zincirini düşürür, diğer zincirlere dokunmaz.
"""

import copy

import pytest

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.app.session import open_session
from nl2sql.datasets import load_dataset
from nl2sql.eval import followups
from nl2sql.schema_map import build

DATASET = load_dataset("synthetic_erp")
CHAINS = followups.load_followups(DATASET)


@pytest.fixture(scope="module")
def erp_db(tmp_path_factory):
    folder = tmp_path_factory.mktemp("eval-followups")
    path = folder / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


@pytest.fixture
def session(erp_db, tmp_path):
    """Kümenin kendi sahte istemcisi: make_client("fake") zincirleri de geçirdiği için hepsi golden."""
    return open_session(
        "synthetic_erp", llm="fake", db_path=erp_db,
        audit_path=tmp_path / "audit.jsonl", ask_log=tmp_path / "asks.jsonl",
    )


@pytest.fixture
def wrong_turn_session(erp_db, tmp_path):
    """F01'in ikinci turu birincinin SQL'iyle cevaplanıyor: o tur ve zinciri yanlış, diğerleri doğru."""
    chains = copy.deepcopy(CHAINS)
    f01 = next(chain for chain in chains if chain["id"] == "F01")
    f01["turns"][1]["sql"] = f01["turns"][0]["sql"]

    def client(mode):
        return fake.for_golden(
            DATASET.golden(), DATASET.fake_fallback_sql, mode=mode,
            ambiguous=DATASET.ambiguous(), followups=chains,
        )

    return open_session(
        "synthetic_erp", llm="fake", db_path=erp_db, client_factory=client,
        audit_path=tmp_path / "wrong-audit.jsonl", ask_log=tmp_path / "wrong-asks.jsonl",
    )


def test_fake_chains_score_full_marks(session, tmp_path):
    metrics = followups.followup_metrics(followups.run_followups(session, CHAINS, tmp_path))

    assert metrics["turns"] == 9 and metrics["chains"] == 3
    assert metrics["turn_accuracy"] == 1.0
    assert metrics["chain_accuracy"] == 1.0
    assert metrics["context_accuracy"] == 1.0


def test_the_store_is_wiped_at_the_start_of_every_run(session, tmp_path):
    followups.run_followups(session, CHAINS, tmp_path)
    stale = tmp_path / "followups" / "onceki.db"
    stale.write_text("stale", encoding="utf-8")

    followups.run_followups(session, CHAINS, tmp_path)

    assert not stale.exists(), "out_dir/followups her koşumda sil-baştan kurulmalı"


def test_a_wrong_turn_fails_its_chain_but_not_the_others(wrong_turn_session, tmp_path):
    items = followups.run_followups(wrong_turn_session, CHAINS, tmp_path)
    metrics = followups.followup_metrics(items)

    assert [row["outcome"] for row in items if row["id"] == "F01"][1] != "pass"
    assert all(row["outcome"] == "pass" for row in items if row["id"] in ("F02", "F03"))
    assert metrics["turn_accuracy"] < 1.0
    assert metrics["chain_accuracy"] < 1.0
    assert metrics["chains"] == 3
