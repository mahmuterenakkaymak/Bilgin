# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T356: the commercial ERP product name appears nowhere a person reads (PLAN Run 8).

The brand is held here only as the sha256 of its lower-cased form, so this file - itself a
tracked path the guard scans - never carries it in clear. A file is "dirty" when the brand's
hash shows up as any length-|brand| window of its lower-cased ASCII words; that is the only
containment test possible when the clear text may not be written down. Machine-output dirs and
the prose that keeps the word as the record of the rule are skipped.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# sha256 of the brand, lower-cased; the clear text is never written in this repo.
_BRAND_SHA256 = "559ec927d80cfa9ed413705e02ef000ad6a6be1dec74d726ee850067b510813b"
_BRAND_LEN = 6  # the brand's length - metadata, not the brand itself

# Machine output, plus the prose that records the rule and keeps the word on purpose.
_EXCLUDED_DIRS = (".hybrid/", "logs/", "eval_out/", "data/")
_EXCLUDED_FILES = {"TASKS.md", "PLAN.md", "REVIEW.md", "VISUAL_REVIEW.md"}

_WORD = re.compile(rb"[a-z]+")


def _hits(data: bytes, digest: str = _BRAND_SHA256, length: int = _BRAND_LEN) -> bool:
    """True when `digest` is the hash of any `length`-wide window inside a lower-cased word run."""
    for run in _WORD.finditer(data):
        word = run.group()
        for start in range(len(word) - length + 1):
            if hashlib.sha256(word[start:start + length]).hexdigest() == digest:
                return True
    return False


def _scanned(rel: str) -> bool:
    if rel.startswith(_EXCLUDED_DIRS) or rel in _EXCLUDED_FILES:
        return False
    return not ("/" not in rel and rel.startswith("PROJECT_BRIEF") and rel.endswith(".md"))


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return out.splitlines()


def test_no_tracked_file_carries_the_brand():
    offenders = []
    for rel in _tracked_files():
        if not _scanned(rel):
            continue
        path = ROOT / rel
        if not path.is_file():  # renamed away but still in the index
            continue
        if _hits(path.read_bytes().lower()):
            offenders.append(rel)
    assert offenders == [], f"marka bu dosyalarda düz metin duruyor: {offenders}"


def test_no_dataset_display_name_carries_the_brand():
    offenders = []
    for pattern in ("datasets/*/dataset.json", "real_datasets/*/dataset.json"):
        for path in ROOT.glob(pattern):
            display = json.loads(path.read_text(encoding="utf-8")).get("display_name", "")
            if _hits(display.encode().lower()):
                offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == [], f"display_name markayı taşıyor: {offenders}"


def test_the_scan_detects_a_planted_word():
    # Positive control with a stand-in word: proves the window scan is not vacuous.
    probe = hashlib.sha256(b"zzzzzz").hexdigest()
    assert _hits(b"a zzzzzz b", probe, 6)
    assert not _hits(b"a yyyyyy b", probe, 6)
