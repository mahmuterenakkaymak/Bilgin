"""``eval-retrieval --dataset X`` raporu kümenin kendi ``eval_out``una yazar (R4-3, R4-4).

Rapor klasörü de kümenin tanımıdır: iki dünya aynı ``eval_out/retrieval/latest``i paylaşırsa
ikincinin koşumu birincinin kıyasını sessizce yutar, yani bir sonraki ``eval`` yanlış öncekiyle
karşılaştırır. Testler kökü geçici bir klasöre alır; böylece "gerçek ``eval_out``a tek dosya
düşmedi" iddiası da ekrandan değil diskten okunur.
"""

import json
import shutil
from pathlib import Path

import pytest

from nl2sql import config
from nl2sql.cli import main as cli

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Proje kökü geçici: kümenin ``eval_out``u oraya düşer, ``config``in sabiti gerçek repoda kalır."""
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(FIXTURE_ROOT))
    return tmp_path


def files_under(root: Path) -> set[Path]:
    """``root`` altındaki dosyaların tam listesi; klasör yoksa boş küme."""
    if not root.exists():
        return set()
    return {path for path in root.rglob("*") if path.is_file()}


def copy_dataset(root: Path, name: str) -> None:
    """Mini kümesinin adı değiştirilmiş kopyası: iki küme, iki ``eval_out``, tek koşum dizisi."""
    folder = root / name
    shutil.copytree(FIXTURE_ROOT / "mini", folder)
    meta = json.loads((folder / "dataset.json").read_text(encoding="utf-8"))
    meta["name"] = name
    meta.setdefault("outputs", {})["eval_out"] = f"eval_out/{name}"
    (folder / "dataset.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def test_the_report_goes_to_the_datasets_own_eval_out(project, capsys):
    before = files_under(config.EVAL_OUT)

    assert cli.eval_retrieval("fake", dataset="mini") == 0
    out = capsys.readouterr().out

    report = project / "eval_out" / "mini" / "retrieval" / "latest" / "report.json"
    assert report.exists()
    assert json.loads(report.read_text(encoding="utf-8"))["questions"]
    # Ekran da raporun nereye yazıldığını söylemeli: kullanıcı hangi klasöre baktığını bilmeli.
    folder = report.parent.parent  # run_dir report.md olarak ekranda yazılır, latest değil
    assert str(folder) in next(line for line in out.splitlines() if line.startswith("Rapor:"))
    assert files_under(config.EVAL_OUT) == before, "gerçek eval_out'a tek dosya düşmemeli"


def test_an_explicit_out_dir_still_wins(project, capsys):
    out_dir = project / "verilen-klasor"

    assert cli.eval_retrieval("fake", out_dir=out_dir) == 0
    capsys.readouterr()

    assert (out_dir / "latest" / "report.json").exists()
    written = [path for path in project.rglob("*") if path.is_file()]
    assert written and all(out_dir in path.parents for path in written)


def test_two_datasets_keep_two_reports(tmp_path, monkeypatch, capsys):
    datasets = tmp_path / "datasets"
    for name in ("mini", "mini2"):
        copy_dataset(datasets, name)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(datasets))

    for name in ("mini", "mini2"):
        assert cli.eval_retrieval("fake", dataset=name) == 0
    capsys.readouterr()

    for name in ("mini", "mini2"):
        assert (tmp_path / "eval_out" / name / "retrieval" / "latest" / "report.json").exists()
