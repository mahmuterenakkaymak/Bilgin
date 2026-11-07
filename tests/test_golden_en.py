# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T401: İngilizce altın küme, Türkçe kümenin birebir çevirisidir (PLAN R8-10).

``golden_en.jsonl`` satırı = Türkçe satırın ``id``'si ``E01..``, ``source_id``'si aynı sıradaki
Türkçe satırın ``id``'si ve İngilizce sorusu; ``sql``, ``ordered``, ``trap``, ``tags``,
``requires_tables``, ``rules`` ve geri kalan her alan aynen kopyadır. İngilizce satır böylece
yeni bir ölçüm istemez: aynı SQL, aynı dünya, aynı tuzak - yalnız cümlesi İngilizce. Her soru
``detect_lang``'tan ``en`` olarak çıkar ve kendi Türkçe sorusundan farklıdır, yani iki kümenin
kaydı sahte istemcide çakışmaz; ``files.golden_en`` olmayan kümede ``golden("en")`` Türkçe
kümenin kendisidir. ``files.followups_en`` için de aynı kural geçerlidir.
"""

import dataclasses
import json

import pytest

from bilgin import datasets
from bilgin.cli import main as cli
from bilgin.datasets import load_dataset
from bilgin.i18n.detect import detect_lang

ALL = {name: load_dataset(name) for name in datasets.list_datasets()}
ENGLISH = {name: ds for name, ds in ALL.items() if ds.golden_en_path is not None}
TURKISH_ONLY = {name: ds for name, ds in ALL.items() if ds.golden_en_path is None}
PAIRS = [
    (name, english, turkish)
    for name in sorted(ENGLISH)
    for english, turkish in zip(ENGLISH[name].golden("en"), ENGLISH[name].golden())
]
PAIR_IDS = [f"{name}::{english['id']}" for name, english, _ in PAIRS]


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


# ------------------------------------------------------------------ the file mirrors the Turkish set


@pytest.mark.parametrize("name", sorted(ENGLISH))
def test_the_english_set_has_the_same_size_and_numbering(name):
    english = ENGLISH[name].golden("en")
    turkish = ENGLISH[name].golden()
    assert len(english) == len(turkish), name
    assert [line["id"] for line in english] == [f"E{n:02d}" for n in range(1, len(turkish) + 1)], name
    assert [line["source_id"] for line in english] == [line["id"] for line in turkish], name


@pytest.mark.parametrize("name", sorted(ENGLISH))
def test_the_source_id_names_the_line_at_the_same_position(name):
    turkish = ENGLISH[name].golden()
    for position, line in enumerate(ENGLISH[name].golden("en")):
        assert turkish[position]["id"] == line["source_id"], f"{name}/{line['id']}"


@pytest.mark.parametrize("name", sorted(ENGLISH))
def test_the_english_ids_are_unique(name):
    ids = [line["id"] for line in ENGLISH[name].golden("en")]
    assert len(ids) == len(set(ids)), name


@pytest.mark.parametrize("name,english,turkish", PAIRS, ids=PAIR_IDS)
def test_every_field_but_the_identity_is_copied(name, english, turkish):
    def without(line, *fields):
        return {key: value for key, value in line.items() if key not in fields}

    assert without(english, "id", "source_id", "question") == without(
        turkish, "id", "question"
    ), f"{name}/{english['id']}"
    assert set(english) == set(turkish) | {"source_id"}, f"{name}/{english['id']}"


@pytest.mark.parametrize("name,english,turkish", PAIRS, ids=PAIR_IDS)
def test_every_english_question_reads_as_english(name, english, turkish):
    assert detect_lang(english["question"]) == "en", f"{name}/{english['id']}"
    assert detect_lang(turkish["question"]) == "tr", f"{name}/{turkish['id']}"
    assert english["question"] != turkish["question"], f"{name}/{english['id']} çevrilmemiş"


def test_the_first_english_question_is_the_one_the_flows_type():
    assert load_dataset("wwi").golden("en")[0]["question"] == (
        "What is the name of each country and how many cities belong to it?"
    )


# ------------------------------------------------------------------ the accessor and its fallback


@pytest.mark.parametrize("name", sorted(TURKISH_ONLY))
def test_a_dataset_without_the_key_answers_english_with_the_turkish_set(name):
    assert TURKISH_ONLY[name].golden("en") == TURKISH_ONLY[name].golden()
    assert TURKISH_ONLY[name].followups("en") == TURKISH_ONLY[name].followups()


@pytest.mark.parametrize("name", sorted(ALL))
def test_a_declared_english_chain_file_replaces_the_turkish_one(name, tmp_path):
    dataset = ALL[name]
    path = tmp_path / "followups_en.jsonl"
    path.write_text(
        json.dumps({"id": "C01", "turns": [{"question": "How many rows came back?"}]}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    with_english = dataclasses.replace(dataset, followups_en_path=path)

    chains = with_english.followups("en")
    assert [turn["question"] for chain in chains for turn in chain["turns"]] == ["How many rows came back?"]
    assert chains[0]["turns"][0]["uses_turns"] == [], "sözleşmenin liste alanı boş varsayılanını alır"
    assert with_english.followups() == dataset.followups()


# ------------------------------------------------------------------ the fake knows both languages


@pytest.mark.parametrize("name", sorted(ENGLISH))
def test_the_fake_replays_the_turkish_and_the_english_lines_together(name):
    client = cli.make_client("fake", "full", ENGLISH[name])
    for english, turkish in zip(ENGLISH[name].golden("en"), ENGLISH[name].golden()):
        assert submitted_sql(client, english["question"]) == english["sql"], english["id"]
        assert submitted_sql(client, turkish["question"]) == turkish["sql"], turkish["id"]
