"""History is per dataset (2026-10-25): one ask log serves every dataset, but clicking another dataset's question
sends it to the wrong database. `dataset=None` is the default dataset, whose records carry no name; leaving the
argument out keeps the old behaviour (every record)."""

from nl2sql.app import asklog


def write(path, *datasets):
    for i, name in enumerate(datasets):
        asklog.record_ask({"audit_id": f"a{i}", "dataset": name, "question": f"q{i}", "status": "answered"}, path)


def test_each_dataset_sees_only_its_own_questions(tmp_path):
    path = tmp_path / "asks.jsonl"
    write(path, None, "wwi_real", "synthetic_erp", "wwi_real", None)
    assert [r["question"] for r in asklog.history(path, dataset="wwi_real")] == ["q3", "q1"]
    assert [r["question"] for r in asklog.history(path, dataset=None)] == ["q4", "q0"]
    assert [r["question"] for r in asklog.history(path, dataset="synthetic_erp")] == ["q2"]


def test_no_dataset_argument_keeps_every_record(tmp_path):
    path = tmp_path / "asks.jsonl"
    write(path, None, "wwi_real")
    assert len(asklog.history(path)) == 2
