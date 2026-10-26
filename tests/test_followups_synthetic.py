"""T301: sentetik ardışık soru zincirleri ve yükleyicisi (PLAN R7-13, Contracts "followup chain").

Burada ölçüm yok, kümenin sözleşmesi var: üç zincir, her turda çalışan bir golden SQL ve
``uses_turns``'in gösterdiği önceki turlar. Zincirleri tur tur çalıştırmak R7-14'in işi; burada
satırların şekli, her SQL'in kurulu dünyada boş döndürmemesi ve chart-only turun bir önceki turun
SQL'ini yinelenmesi doğrulanır.
"""

import json

import pytest
from pathlib import Path

from nl2sql import config
from nl2sql.datasets import load_dataset
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget
from nl2sql.schema_map import build

DATASET = load_dataset("synthetic_erp")
CHAINS = DATASET.followups()
IDS = [chain["id"] for chain in CHAINS]

# Golden turlar karşılaştırılacağı için satır kesilmez (PLAN Decision 8).
COMPARE = Budget(max_rows=config.COMPARE_MAX_ROWS)
TURN_FIELDS = {"question", "sql", "uses_turns", "tags"}

MINI_DOC = {
    "name": "mini",
    "as_of": "2026-01-31",
    "builder": "builder.py:build_db",
    "generator": "builder.py:generate",
    "references": "builder.py:REFERENCES",
}


@pytest.fixture(scope="module")
def executor(tmp_path_factory):
    """Tohum 42'nin SQLite dünyası ve o dünyaya bakan tek kapı."""
    folder = tmp_path_factory.mktemp("followups-synthetic")
    path = folder / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return LocalExecutor("sqlite", path, audit_path=folder / "audit.jsonl")


@pytest.fixture(scope="module")
def results(executor):
    """Her turun golden SQL'inin kurulu dünyadaki sonucu; şekil testi aynı çalışmayı paylaşır."""
    return {
        chain["id"]: [executor.execute(turn["sql"], COMPARE, chain["id"]) for turn in chain["turns"]]
        for chain in CHAINS
    }


def write_mini(root, files: dict, followups: str | None = None):
    """``root`` altında yalnız ``dataset.json``'u olan bir küme klasörü; ``files`` sözleşmenin dosyaları."""
    folder = root / "mini"
    folder.mkdir(parents=True)
    doc = dict(MINI_DOC, files=files)
    (folder / "dataset.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    if followups is not None:
        (folder / "followups.jsonl").write_text(followups, encoding="utf-8")
    return folder


# ------------------------------------------------------------------ the chains


def test_the_set_is_wired_into_the_dataset():
    assert DATASET.followups_path == DATASET.root / "followups.jsonl"
    assert DATASET.followups_path.is_file()
    assert IDS == ["F01", "F02", "F03"]


def test_every_line_has_the_contract_shape():
    for chain in CHAINS:
        assert {"id", "tags", "turns"} <= set(chain)
        assert chain["id"] and chain["tags"] and chain["turns"]
        for turn in chain["turns"]:
            assert TURN_FIELDS == set(turn), f"{chain['id']}: {sorted(turn)}"
            assert turn["question"].strip() and turn["sql"].strip()
            assert isinstance(turn["tags"], list)
            assert all(isinstance(n, int) and n >= 1 for n in turn["uses_turns"])


@pytest.mark.parametrize("chain", CHAINS, ids=IDS)
def test_uses_turns_point_at_earlier_turns(chain):
    for number, turn in enumerate(chain["turns"], start=1):
        assert all(n < number for n in turn["uses_turns"]), f"{chain['id']} tur {number}"


def test_the_chains_ask_the_planned_questions():
    questions = {chain["id"]: [turn["question"] for turn in chain["turns"]] for chain in CHAINS}
    assert questions["F01"] == [
        "Eylül 2026'da en çok satan 5 ürün hangileri; kodu, adı ve toplam satış miktarı nedir?",
        "Bunlardan hangisi en çok ciro yaptı?",
        "Grafiği pasta yap",
    ]
    assert questions["F02"] == [
        "2026 yılında aylık KDV hariç satış cirosu nedir?",
        "Sadece Ankara'daki carilere yapılan satışlar",
        "Grafiği çubuk yap",
    ]
    assert questions["F03"] == [
        "Ankara'da faaliyet gösteren alıcı carilerin kodu ve ünvanı nedir?",
        "Peki toplam kaç ürün var?",
        "Bu carilerin Eylül 2026 satış faturası toplamı ne kadar?",
    ]


def test_uses_turns_are_the_planned_ones():
    # F03'ün ortası tek başına durur: önceki tura bakmaz, üçüncü tur birinci carilere döner.
    assert {chain["id"]: [turn["uses_turns"] for turn in chain["turns"]] for chain in CHAINS} == {
        "F01": [[], [1], [2]],
        "F02": [[], [1], [2]],
        "F03": [[], [], [1]],
    }


@pytest.mark.parametrize("chain", CHAINS, ids=IDS)
def test_chart_only_turns_repeat_the_previous_sql(chain):
    for number, turn in enumerate(chain["turns"], start=1):
        if "chart_only" not in turn["tags"]:
            continue
        assert turn["sql"] == chain["turns"][number - 2]["sql"], f"{chain['id']} tur {number}"
        assert turn["uses_turns"] == [number - 1]


@pytest.mark.parametrize("chain", CHAINS, ids=IDS)
def test_every_turn_sql_runs_on_the_built_world(chain, results):
    for number, (turn, result) in enumerate(zip(chain["turns"], results[chain["id"]]), start=1):
        where = f"{chain['id']} tur {number}: {turn['question']}"
        assert result.error is None, f"{where} -> {result.error}"
        assert result.rows, f"{where} boş döndü; tur hiçbir şey ölçmüyor"


# ------------------------------------------------------------------ a dataset without the file


def test_a_dataset_without_the_key_has_no_followups():
    # Updated 2026-10-26 (Eren: "otomatik olsun"): wwi gained this file for the visual flows (Run 8 brief); mini has none.
    mini = load_dataset("mini", root=Path(__file__).parent / "fixtures" / "datasets")
    assert mini.followups_path is None
    assert mini.followups() == []


def test_a_key_without_a_file_has_no_followups(tmp_path):
    folder = write_mini(tmp_path, {"followups": "followups.jsonl"})
    dataset = load_dataset("mini", root=tmp_path)
    assert dataset.followups_path == folder / "followups.jsonl"
    assert dataset.followups() == []


def test_list_fields_get_their_empty_defaults(tmp_path):
    line = '{"id": "F01", "turns": [{"question": "tohum kaç", "sql": "SELECT 1"}]}'
    write_mini(tmp_path, {"followups": "followups.jsonl"}, line + "\n\n")
    assert load_dataset("mini", root=tmp_path).followups() == [
        {
            "id": "F01",
            "tags": [],
            "turns": [{"question": "tohum kaç", "sql": "SELECT 1", "uses_turns": [], "tags": []}],
        }
    ]
