import importlib


def test_packages_import():
    for name in [
        "nl2sql",
        "nl2sql.schema_map",
        "nl2sql.policy",
        "nl2sql.engine",
        "nl2sql.agent",
        "nl2sql.eval",
        "nl2sql.cli",
        "eval",
    ]:
        importlib.import_module(name)
