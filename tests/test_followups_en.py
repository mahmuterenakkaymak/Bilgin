# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T420: ``wwi`` İngilizce ardışık soru zincirleri (PLAN R8-10).

``followups_en.jsonl`` aynı kuralı zincirlerde izler: ``FE01..`` kimliği, tur tur çevrilmiş sorusu,
kopya SQL'i, ``uses_turns``i ve etiketleri - aynı sorgu, aynı dünya, yalnız cümlesi İngilizce.
Bağlam bloğu modelin yüzüne yazıldığı için Türkçe kalır (R7-4), dolayısıyla sahtenin zinciri tanıyan
anahtarı - soru ile ``Tur n sorusu:`` satırlarından okuduğu önceki sorular - İngilizce sorularda da
değişmeden çalışır; ``make_client("fake")`` zincirlerin İngilizcesini de yüklemekten başka bir şey
yapmaz. Ölçüm gerçek kapıdan: kümenin kendi builder'ının kurduğu dosya, gerçek ``cli.evaluate``,
``--followups --lang en --llm fake``.
"""

import json

import pytest
from pytest import MonkeyPatch

from bilgin.cli import main as cli
from bilgin.datasets import load_dataset
from bilgin.i18n.detect import detect_lang
from bilgin.policy import pii, policy
from bilgin.schema_map import doc

DATASET = load_dataset("wwi")
SCHEMA = DATASET.schema()
ALLOWLIST = doc.allowlist(SCHEMA)
CHAINS = DATASET.followups()
EN_CHAINS = DATASET.followups("en")
TURNS = [
    (english, turkish, number, turn)
    for english, turkish in zip(EN_CHAINS, CHAINS)
    for number, turn in enumerate(english["turns"], start=1)
]
TURN_IDS = [f"{chain['id']}/{number}" for chain, _, number, _ in TURNS]


def submitted_sql(client, question: str) -> str:
    """Sahtenin bu soruyu hangi SQL ile kapattığı: kayıt tanımadığı soruyu yedek sorguya düşürür."""
    messages = [{"role": "user", "content": question}]
    for _ in range(4):
        response = client.chat(messages)
        call = response.tool_calls[0]
        if call.name == "submit_sql":
            return str(call.arguments.get("sql", ""))
        messages.append({"role": "assistant", "content": response.content, "tool_calls": [call]})
        messages.append({"role": "tool", "tool_call_id": call.id, "content": "ok"})
    return ""


def verdict_of(sql: str):
    return policy.check(
        sql,
        ALLOWLIST,
        pii=pii.column_map(SCHEMA),
        deny=pii.deny_set(SCHEMA),
        keys=pii.count_keys(SCHEMA),
    )


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Modül boyunca tek kurulum: wwi builder'ının dosyası ve audit'i tek tmp klasörde.

    Kabukta ambiyans duran ``BILGIN_MSSQL_CONN``/``BILGIN_BACKEND`` silinir: küme SQLite'ı kendi
    taşır (R7-29), yani ölçümün kapısı hiçbir zaman canlı sunucuya dönmez.
    """
    root = tmp_path_factory.mktemp("followups-en")
    mp = MonkeyPatch()
    mp.delenv("BILGIN_MSSQL_CONN", raising=False)
    mp.delenv("BILGIN_BACKEND", raising=False)
    database = root / "wwi.db"
    try:
        DATASET.build_db(db_path=database, sql_path=root / "wwi.sql")
        yield database, root / "audit.jsonl"
    finally:
        mp.undo()


# ------------------------------------------------------------------ the file is the one declared


def test_the_english_chains_are_the_ones_the_dataset_declares():
    assert DATASET.followups_en_path == DATASET.root / "followups_en.jsonl"
    assert DATASET.followups_en_path.is_file()
    assert DATASET.followups("en") != DATASET.followups()


def test_the_english_chains_have_the_same_ids_tags_and_turn_counts():
    assert [chain["id"] for chain in EN_CHAINS] == [f"FE{n:02d}" for n in range(1, len(CHAINS) + 1)]
    for english, turkish in zip(EN_CHAINS, CHAINS):
        assert english["tags"] == turkish["tags"], english["id"]
        assert len(english["turns"]) == len(turkish["turns"]), english["id"]


# ------------------------------------------------------------------ every turn mirrors its twin


@pytest.mark.parametrize("chain,turkish_chain,number,turn", TURNS, ids=TURN_IDS)
def test_every_english_turn_copies_the_turkish_sql_and_the_back_references(
    chain, turkish_chain, number, turn
):
    turkish = turkish_chain["turns"][number - 1]
    assert turn["sql"] == turkish["sql"], f"{chain['id']} tur {number}"
    assert turn["uses_turns"] == turkish["uses_turns"], f"{chain['id']} tur {number}"
    assert turn["tags"] == turkish["tags"], f"{chain['id']} tur {number}"
    assert turn["question"] != turkish["question"], f"{chain['id']} tur {number} çevrilmemiş"


@pytest.mark.parametrize("chain,turkish_chain,number,turn", TURNS, ids=TURN_IDS)
def test_every_english_turn_question_reads_as_english(chain, turkish_chain, number, turn):
    turkish = turkish_chain["turns"][number - 1]
    assert detect_lang(turn["question"]) == "en", f"{chain['id']} tur {number}"
    assert detect_lang(turkish["question"]) == "tr", f"{turkish_chain['id']} tur {number}"


@pytest.mark.parametrize("chain,turkish_chain,number,turn", TURNS, ids=TURN_IDS)
def test_every_english_turn_sql_passes_the_policy(chain, turkish_chain, number, turn):
    verdict = verdict_of(turn["sql"])
    assert verdict.ok, f"{chain['id']} tur {number}: {verdict.reason}"
    assert verdict.tables <= ALLOWLIST, f"{chain['id']} tur {number}"


# ------------------------------------------------------------------ the fake knows both languages


def test_the_fake_replays_the_turkish_and_the_english_first_turns():
    client = cli.make_client("fake", "full", DATASET)
    for english, turkish in zip(EN_CHAINS, CHAINS):
        assert submitted_sql(client, english["turns"][0]["question"]) == (
            english["turns"][0]["sql"]
        ), english["id"]
        assert submitted_sql(client, turkish["turns"][0]["question"]) == (
            turkish["turns"][0]["sql"]
        ), turkish["id"]


# ------------------------------------------------------------------ the measurement on the real door


def test_the_english_followups_run_scores_full_marks(world, tmp_path, capsys):
    database, audit = world
    out_dir = tmp_path / "eval_out"
    code = cli.evaluate(
        cli.make_client("fake", "full", DATASET),
        mode="full",
        db_path=database,
        audit_path=audit,
        out_dir=out_dir,
        dataset="wwi",
        followups=True,
        lang="en",
    )
    data = json.loads((out_dir / "latest" / "report.json").read_text(encoding="utf-8"))
    text = (out_dir / "latest" / "report.md").read_text(encoding="utf-8")
    followups = data["followups"]

    assert code == 0 and data["lang"] == "en"
    assert followups["turn_accuracy"] == 1.0
    assert followups["chain_accuracy"] == 1.0
    assert followups["context_accuracy"] == 1.0
    assert followups["chains"] == len(EN_CHAINS)
    assert followups["turns"] == sum(len(chain["turns"]) for chain in EN_CHAINS)
    assert {item["id"] for item in followups["items"]} == {chain["id"] for chain in EN_CHAINS}

    # Ölçülen zincir İngilizce olanıdır: tabloda İngilizce sorular duruyor, Türkçeleri düşmüyor.
    for chain in EN_CHAINS:
        assert f"### {chain['id']}" in text
        for turn in chain["turns"]:
            assert turn["question"] in text
    for chain in CHAINS:
        for turn in chain["turns"]:
            assert turn["question"] not in text
