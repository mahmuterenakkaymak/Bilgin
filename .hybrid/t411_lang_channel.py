import pathlib
import re

path = pathlib.Path("nl2sql/cli/main.py")
lines = path.read_text(encoding="utf-8").splitlines(keepends=True)

# R8-11: bu komutlar dili ``main``in çözdüğü ``_LANG``dan okur - kwargs sözleşmesi testte donuk.
TARGET = {
    "build_database",
    "build_index",
    "import_map",
    "introspect_schema",
    "diff_map",
    "merge_map",
    "make_login_script",
    "serve",
    "_embed_arg",
    "_dataset_line",
    "_mapping_lines",
    "_read_mapping",
    "_read_schema",
    "_introspect_db",
    "_embed_failed",
    "_served_dataset",
    "_no_db",
}

out = []
current = None
sigs = 0
calls = 0
for line in lines:
    match = re.match(r"def (\w+)\(", line)
    if match:
        current = match.group(1)
    if current in TARGET:
        line, n = re.subn(r'    lang: str = "tr",', "    lang: str | None = None,", line)
        sigs += n
        line, n = re.subn(
            r'lang: str = "tr"\)', "lang: str | None = None)", line
        )
        sigs += n
        new, n = re.subn(r"(?<![A-Za-z0-9_])t\(", "_t(", line)
        if n:
            calls += n
            line = new
    out.append(line)

path.write_text("".join(out), encoding="utf-8")
print("signatures:", sigs, "calls:", calls)
