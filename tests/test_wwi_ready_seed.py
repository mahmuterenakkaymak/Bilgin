# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T389: wwi kümesinin tohum hazır soruları (PLAN R7-19).

``datasets/wwi``nin tohumu da altın kaydın cümlesidir: dört iş rolünün her birine iki kart, bir de
herkesin ekranındaki tek ortak kart. Satırın süzgeci politika, yürütmesi kümenin kendi builder'ının
kurduğu dosyadır - yani tahtada görünen her cümle bu dünyada gerçekten koşar. wwi_real'in tohumu
SQL Server'da koştuğu için onun testi yalnız kendi allowlist'ına bakıyor
(``tests/test_ready_seed.py``); buranın dünyası yerel SQLite, dolayısıyla yürütmenin kendisi de
ölçülüyor.
"""

import pytest

from bilgin import config, datasets
from bilgin.auth.store import UserStore
from bilgin.engine.executor import LocalExecutor
from bilgin.engine.result import Budget
from bilgin.policy import policy
from bilgin.schema_map import doc
from bilgin.start.ready import DISPLAYS, EVERY_ROLE, ReadyStore
from bilgin.start.seed import SETTING, ensure_seeded

WWI = "wwi"
# Tohumun taşıdığı roller: ``genel``in yerini ``*`` tutuyor, o yüzden dört rolün ikişer kartı var.
ROLES = ("satis", "satin_alma", "muhasebe", "yonetim")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Kümenin kendi builder'ının kurduğu dosya ve ona bakan tek gerçek yürütücü."""
    folder = tmp_path_factory.mktemp("wwi_seed")
    ds = datasets.load_dataset(WWI)
    database = folder / "wwi.db"
    ds.build_db(db_path=database, sql_path=folder / "wwi.sql")
    executor = LocalExecutor(
        "sqlite",
        database,
        doc.allowlist(ds.schema()),
        folder / "audit.jsonl",
        pii_schema=ds.schema(),
    )
    return ds, executor


# --------------------------------------------------------------------- kümenin tohum sözleşmesi


def test_every_dataset_folder_declares_its_seed():
    root = config.datasets_dir()

    for name in datasets.list_datasets(root):
        ds = datasets.load_dataset(name, root=root)
        assert ds.ready_questions_path is not None, f"{name}: files.ready_questions yok"
        assert ds.ready_questions_path.is_file(), f"{name}: {ds.ready_questions_path} yok"


def test_the_four_roles_and_the_common_one_are_covered():
    roles = [line["business_role"] for line in datasets.load_dataset(WWI).ready_questions()]

    for role in ROLES:
        assert roles.count(role) == 2, f"{role}: iki kart olmalı"
    assert roles.count(EVERY_ROLE) == 1, "herkesin ekranındaki tek ortak kart"
    assert set(roles) == set(ROLES) | {EVERY_ROLE}


def test_the_seeds_carry_every_display():
    lines = datasets.load_dataset(WWI).ready_questions()

    assert {line["display"] for line in lines} == set(DISPLAYS)


# ---------------------------------------------------------------- süzgeç ve kurulu dünyada yürüyüş


def test_every_seed_line_passes_the_allowlist_and_runs_on_the_built_db(world):
    ds, executor = world
    allowlist = doc.allowlist(ds.schema())
    golden = {line["sql"] for line in ds.golden()}

    for line in ds.ready_questions():
        assert line["sql"] in golden, f"{line['title']}: altın kayıtta olmayan cümle"
        verdict = policy.check(line["sql"], allowlist, config.TOP_N)
        assert verdict.ok, f"{line['title']}: {verdict.reason}"
        result = executor.execute(line["sql"], Budget(max_rows=config.UI_MAX_ROWS), "seed")
        assert result.error is None, f"{line['title']}: {result.error}"
        assert result.rows, f"{line['title']}: boş sonuç"


# ------------------------------------------------------------------------------ bir kez tohumlama


def test_ensure_seeded_stores_every_line_approved(tmp_path, world):
    ds, executor = world
    lines = ds.ready_questions()
    store, users = ReadyStore(tmp_path / "app.db"), UserStore(tmp_path / "app.db")

    assert ensure_seeded(store, users, ds, executor) == len(lines)

    cards = store.list_all(WWI)
    assert len(cards) == len(lines), "hiçbir satır düşmez"
    assert all(card["approved"] for card in cards), "tohum satırı onaylı doğar"
    assert users.get_setting(SETTING.format(name=WWI)) == str(len(lines))
