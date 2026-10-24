import os
import shutil
import subprocess

ROOT = os.path.abspath("..")
DEST = os.path.join(ROOT, "_t101check", "repo")
if os.path.exists(DEST):
    shutil.rmtree(DEST)

TOP_SKIP = {".venv", ".git", "_t101check", ".hybrid", "data", "logs", "index", "eval_out", ".pytest_cache"}

def ignore(directory, names):
    if os.path.abspath(directory) == ROOT:
        return [n for n in names if n in TOP_SKIP]
    return [n for n in names if n == "__pycache__"]

shutil.copytree(ROOT, DEST, ignore=ignore)

FILES = [
    "schema/schema.json",
    "tests/test_excel_fixtures.py",
    "tests/test_integration_m7.py",
    "tests/test_schema_data_tables.py",
    "tests/fixtures/map_customer_map.xlsx",
    "tests/fixtures/map_netsis_style.xlsx",
    "nl2sql/policy/policy.py",
]
for f in FILES:
    data = subprocess.check_output(["git", "-C", ROOT, "show", "HEAD:" + f])
    with open(os.path.join(DEST, f), "wb") as handle:
        handle.write(data)
m9 = os.path.join(DEST, "tests", "test_integration_m9.py")
if os.path.exists(m9):
    os.remove(m9)
print("done")
