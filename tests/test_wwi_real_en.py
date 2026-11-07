# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T419: ``wwi_real`` İngilizce altın ve zincir kümeleri (PLAN R8-10).

Küme yalnız gerçek SQL Server'da koştuğu için İngilizce satırlar burada ölçülmez; sözleşmeleri
sınanır. ``golden_en.jsonl`` satırı = Türkçe satırın ``id``'si ``E01..E26``, ``source_id``'si aynı
sıradaki Türkçe satırın ``id``'si ve İngilizce sorusu; ``sql``, ``ordered``, ``trap``, ``notes``,
``tags``, ``requires_tables``, ``rules`` ve geri kalan her alan aynen kopyadır - aynı sorgu, aynı
dünya, yalnız cümlesi İngilizce. ``followups_en.jsonl`` aynı kuralı zincirlerde izler: ``FE01..``
kimliği, tur tur çevrilmiş sorusu, kopya SQL'i, ``uses_turns`` ve etiketleri. İki dosyanın her
sorgusu kümenin kendi allowlist'i + PII/red kümeleriyle policy'den geçer ve her İngilizce soru
``detect_lang``'tan ``en`` olarak çıkar; gerçek sunucudaki ``eval --lang en`` koşusu README'nin
elle adımıdır.
"""

import pytest

from bilgin.cli import main as cli
from bilgin.datasets import load_dataset
from bilgin.i18n.detect import detect_lang
from bilgin.policy import pii, policy
from bilgin.schema_map import doc

DATASET = load_dataset("wwi_real")
SCHEMA = DATASET.schema()
ALLOWLIST = doc.allowlist(SCHEMA)
GOLDEN = DATASET.golden()
ENGLISH = DATASET.golden("en")
PAIRS = list(zip(ENGLISH, GOLDEN))
PAIR_IDS = [f"wwi_real::{english['id']}" for english, _ in PAIRS]
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


# ------------------------------------------------------------------ the two files are declared


def test_the_english_files_are_the_ones_the_dataset_declares():
    assert DATASET.golden_en_path == DATASET.root / "golden_en.jsonl"
    assert DATASET.followups_en_path == DATASET.root / "followups_en.jsonl"
    assert DATASET.golden_en_path.is_file() and DATASET.followups_en_path.is_file()
    assert DATASET.golden("en") != DATASET.golden()
    assert DATASET.followups("en") != DATASET.followups()


# ------------------------------------------------------------------ the golden set mirrors the Turkish one


def test_the_english_set_has_the_same_size_and_numbering():
    assert len(ENGLISH) == len(GOLDEN)
    assert [line["id"] for line in ENGLISH] == [f"E{n:02d}" for n in range(1, len(GOLDEN) + 1)]
    assert [line["source_id"] for line in ENGLISH] == [line["id"] for line in GOLDEN]


def test_the_source_id_names_the_line_at_the_same_position():
    for position, line in enumerate(ENGLISH):
        assert GOLDEN[position]["id"] == line["source_id"], line["id"]


def test_the_english_ids_are_unique():
    ids = [line["id"] for line in ENGLISH]
    assert len(ids) == len(set(ids)), ids


@pytest.mark.parametrize("english,turkish", PAIRS, ids=PAIR_IDS)
def test_every_field_but_the_identity_is_copied(english, turkish):
    def without(line, *fields):
        return {key: value for key, value in line.items() if key not in fields}

    assert without(english, "id", "source_id", "question") == without(turkish, "id", "question")
    assert set(english) == set(turkish) | {"source_id"}


@pytest.mark.parametrize("english,turkish", PAIRS, ids=PAIR_IDS)
def test_every_english_question_reads_as_english(english, turkish):
    assert detect_lang(english["question"]) == "en", english["id"]
    assert detect_lang(turkish["question"]) == "tr", turkish["id"]
    assert english["question"] != turkish["question"], f"{english['id']} çevrilmemiş"


@pytest.mark.parametrize("english", ENGLISH, ids=[line["id"] for line in ENGLISH])
def test_every_english_golden_sql_passes_the_policy(english):
    verdict = verdict_of(english["sql"])
    assert verdict.ok, f"{english['id']}: {verdict.reason}"
    assert verdict.tables <= ALLOWLIST, english["id"]


# ------------------------------------------------------------------ the chains mirror the Turkish ones


def test_the_english_chains_have_the_same_ids_tags_and_turn_counts():
    assert [chain["id"] for chain in EN_CHAINS] == [f"FE{n:02d}" for n in range(1, len(CHAINS) + 1)]
    for english, turkish in zip(EN_CHAINS, CHAINS):
        assert english["tags"] == turkish["tags"], english["id"]
        assert len(english["turns"]) == len(turkish["turns"]), english["id"]


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
    assert detect_lang(turn["question"]) == "en", f"{chain['id']} tur {number}"


@pytest.mark.parametrize("chain,turkish_chain,number,turn", TURNS, ids=TURN_IDS)
def test_every_english_turn_sql_passes_the_policy(chain, turkish_chain, number, turn):
    verdict = verdict_of(turn["sql"])
    assert verdict.ok, f"{chain['id']} tur {number}: {verdict.reason}"
    assert verdict.tables <= ALLOWLIST, f"{chain['id']} tur {number}"


# ------------------------------------------------------------------ the fake knows both languages


def test_the_fake_replays_the_turkish_and_the_english_lines_together():
    client = cli.make_client("fake", "full", DATASET)
    for english, turkish in PAIRS:
        assert submitted_sql(client, english["question"]) == english["sql"], english["id"]
        assert submitted_sql(client, turkish["question"]) == turkish["sql"], turkish["id"]
