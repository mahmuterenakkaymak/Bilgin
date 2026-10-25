"""T155: M13 entegrasyonu — gerçek profil dosyası, gerçek pencere, gerçek ölçüm.

Elle kurulmuş ``QuestionResult`` yok: profiller gerçek ``config/models.json``dan okunur (tek ekleme
tmp kopyasındaki dar pencere), hücreler gerçek ``compare_models_cmd``in gerçek altın kayıt + gerçek
döngü + gerçek kapı + gerçek indeks üzerinden ölçtüğü hücreler, auto çözümü gerçek ``resolve_auto``
ve gerçek ``ask``. Fazın iddiası dört cümle: iki dünyanın iki penceresinin dört hücresi de raporda
durur ve json Contracts'ın anahtar kümelerinden şaşmaz; Strata her soruyu her iki modda taşımazdan
geçer; dar pencere tam kurallı istemi hiç gönderemez ama gönderdiği her istem kendi sınırının
altındadır; ``--mode auto`` aynı 16K profilini wwi'de tam kurallıya, sentetik dünyada rag'e çözer ve
seçtiğini ekrana söyler.
"""

import json
from pathlib import Path

import pytest

from nl2sql import config, datasets
from nl2sql.agent import llm
from nl2sql.cli import main as cli

DATASETS = ("wwi", "wwi")
WIDE = "strata"
TINY = "tiny"
WINDOW = "qwen27b-16k"
MODES = list(config.COMPARE_MODEL_MODES)
# Contracts (Run 4 additions): model karşılaştırma raporunun ve hanesinin anahtar kümeleri.
REPORT_KEYS = {
    "timestamp",
    "dataset",
    "questions",
    "repeat",
    "models",
    "modes",
    "cells",
    "skipped",
}
CELL_KEYS = {
    "profile",
    "scores",
    "answered_pct",
    "peak_estimate",
    "peak_reported",
    "overflows",
    "trimmed",
    "seconds_per_question",
    "tags",
    "outcomes",
}
PROFILE_KEYS = {"model", "context_budget", "prompt_limit"}
STATS_KEYS = {"mean", "min", "max"}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Profil dosyası: gerçek ``config/models.json`` + tmp kopyasında tek bir dar pencere.

    Dar pencere 4.096 tokenın 3.584'ü: iki dünyanın tam kurallı istemine yetmez, rag'in
    kırpılabilen araç cevaplarına yeter — yani aynı pencere bir modu taşırır, diğerini taşırır.
    """
    folder = tmp_path_factory.mktemp("m13")
    raw = json.loads(Path(config.MODELS_PATH).read_text(encoding="utf-8"))
    assert {WIDE, WINDOW} <= set(raw["profiles"]), "ölçülen pencereler repoda duranlardır"
    raw["profiles"][TINY] = {
        "base_url": "http://127.0.0.1:9/v1",  # discard portu: sahte kayıtta uç nokta hiç aranmaz
        "model": "kisa-pencere",
        "context_budget": 4096,
        "max_output_tokens": 512,
    }
    models = folder / "models.json"
    models.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    built = {}
    for name in DATASETS:
        ds = datasets.load_dataset(name)
        database = folder / f"{name}.db"
        ds.build_db(db_path=database, sql_path=folder / f"{name}.sql")
        index = folder / "index" / name
        assert cli.build_index("fake", dataset=name, index_dir=index) == 0
        built[name] = (ds, database, index, folder / "eval_out" / name)
    return models, built


@pytest.fixture(scope="module")
def compares(world):
    """Her iki dünyada tek gerçek model karşılaştırması: koşumun json'u ve markdown'ı."""
    models, built = world
    reports = {}
    for name, (_, database, index, out) in built.items():
        assert cli.compare_models_cmd(
            models=[WIDE, TINY],
            dataset=name,
            llm_kind="fake",
            models_file=str(models),
            db_path=database,
            index_dir=index,
            out_dir=out,
            audit_path=out / "audit.jsonl",
        ) == 0
        data = next(out.rglob(f"compare_{name}_*.json"))
        reports[name] = (
            json.loads(data.read_text(encoding="utf-8")),
            data.with_suffix(".md").read_text(encoding="utf-8"),
        )
    return reports


# ------------------------------------------------- dört hücre ve Contracts'ın anahtarları


@pytest.mark.parametrize("name", DATASETS)
def test_the_compare_validates_against_the_contract(name, world, compares):
    models, built = world
    data, _ = compares[name]

    assert set(data) == REPORT_KEYS
    assert data["dataset"] == name and data["skipped"] == {}
    assert data["models"] == [WIDE, TINY] and data["modes"] == MODES
    assert data["questions"] == len(built[name][0].golden()) and data["repeat"] == 1
    for cells in data["cells"].values():
        for cell in cells.values():
            assert set(cell) == CELL_KEYS
            assert set(cell["profile"]) == PROFILE_KEYS
            assert set(cell["scores"]) == STATS_KEYS
            assert all(set(stats) == STATS_KEYS for stats in cell["tags"].values())
            assert set(cell["outcomes"]) == {line["id"] for line in built[name][0].golden()}
            assert all(len(runs) == data["repeat"] for runs in cell["outcomes"].values())
    # Hanenin penceresi gerçek profilin penceresidir: rapor uydurma bir bütçe söylemez.
    profile = llm.get_profile(WIDE, models)
    assert data["cells"][WIDE][MODES[0]]["profile"] == {
        "model": profile.model,
        "context_budget": profile.context_budget,
        "prompt_limit": profile.prompt_limit,
    }


def test_the_markdown_shows_every_model_x_mode_cell(compares):
    for name, (_, markdown) in compares.items():
        assert "# Model karşılaştırması — " in markdown
        for model in (WIDE, TINY):
            for mode in MODES:
                assert f"| {model} | {mode} |" in markdown, f"{name}: {model}/{mode} satırı yok"


# ------------------------------------------------- geniş pencere: her soru, iki mod, taşma yok


@pytest.mark.parametrize("name", DATASETS)
def test_the_wide_window_passes_every_question_without_overflow(name, world, compares):
    _, built = world
    data, _ = compares[name]
    total = len(built[name][0].golden())

    for mode in MODES:
        cell = data["cells"][WIDE][mode]
        assert cell["overflows"] == 0 and cell["trimmed"] == 0
        assert cell["answered_pct"] == 100
        assert cell["scores"] == {"mean": total, "min": total, "max": total}
        assert all(outcome == "pass" for runs in cell["outcomes"].values() for outcome in runs)


# ------------------------------------------------- dar pencere: taşırır, ama sınırını aşmaz


@pytest.mark.parametrize("name", DATASETS)
def test_the_tiny_window_overflows_and_stays_under_its_own_limit(name, world, compares):
    models, _ = world
    limit = llm.get_profile(TINY, models).prompt_limit
    data, _ = compares[name]

    for mode, cell in data["cells"][TINY].items():
        outcomes = {outcome for runs in cell["outcomes"].values() for outcome in runs}
        # Sahte kayıt deterministiktir: bir hücre ya hep submit eder ya hep taşar.
        assert outcomes in ({"pass"}, {"context_overflow"}), f"{mode}: {outcomes}"
        if outcomes == {"context_overflow"}:
            assert cell["overflows"] > 0 and cell["answered_pct"] == 0
        else:
            # Hanenin tepe tahmini submit eden koşuların max'ıdır; hepsi submit ettiğine göre
            # bu sayı submit eden HER koşunun isteminin pencerenin altında kaldığını söyler.
            assert cell["peak_estimate"] <= limit

    # Aynı pencere tam kurallı istemi hiç gönderemez, rag'in kırpılabilen bağlamını taşır.
    assert data["cells"][TINY]["full_rules"]["overflows"] > 0
    assert data["cells"][TINY]["rag"]["answered_pct"] == 100


# ------------------------------------------------- auto: aynı profil iki dünyada iki mod


@pytest.mark.parametrize("name", DATASETS)
def test_auto_under_the_16k_profile_resolves_and_says_its_mode(name, world, capsys):
    models, built = world
    ds, database, index, out = built[name]
    profile = llm.get_profile(WINDOW, models)
    threshold = cli._auto_limit(profile)

    mode, estimate = cli.resolve_auto(
        ds.schema(), ds.rules(), index, ds.as_of, ds.name, max_tokens=threshold
    )
    code = cli.ask(
        ds.golden()[0]["question"],
        cli.make_client("fake", mode, ds, profile),
        mode=mode,
        estimate=estimate,
        dataset=name,
        db_path=database,
        index_dir=index,
        audit_path=out / "audit.jsonl",
        profile=profile,
    )
    shown = capsys.readouterr().out

    assert code == 0
    assert mode == ("full_rules" if estimate <= threshold else "rag")
    assert f"Mod: auto -> {mode} (bağlam tahmini " in shown
    assert f"· bütçe {threshold:,}".replace(",", ".") in shown, "eşik pencerenin yarısıdır (R4-12)"
    assert f"Model: {WINDOW} ({profile.model}, bütçe " in shown
