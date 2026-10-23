# REVIEW M7 (T77-T85)

Base 898f67c (Run 3 plan) -> HEAD 836123f. Suite: 1956 passed, green. T77 consolidation verified: every per-question check of the deleted files lives in test_golden_all.py; the dropped m2 budget-fit assertions (row_count==len(rows), truncated False) are subsumed by the equality (truncated rows could never equal the full reference).

- **BUG (T110)**: `import-map notes.txt` (or .csv, legacy .xls, encrypted workbook) dies with an openpyxl `InvalidFileException` traceback - `import_map` catches only OSError/BadZipFile/SheetError; T84 promises friendly exit 2, no traceback, for user-fixable input.
- **BUG (T111)**: `convert` ignores the mapping's `header_row` - a field the producer (propose) writes, the contract carries and the CLI tells the user to edit, but `_convert_sheet` always recomputes the header row; a sheet whose title row has 3+ text cells is unimportable even after editing the mapping (verified: edited header_row=2 -> 0 tables, real header reported "TABLO boş").
- ASSUMPTIONs rechecked: TÜR->data_type priority matches the dictionary order and both fixtures; blank-row padding and blank-TABLO repeat match brief §2; exit 2 for bad input matches T84. All correct.
- Risk: `--mapping` prints the file's stale `disagreements` - after the user fixes the column, "⚠ uyuşmuyor" lines keep printing for a mapping that no longer disagrees.
- Risk: `_merge` writes `generated_by: "llm"` even when every proposal entry was dropped - the file claims llm while the content is pure fallback.
- Risk: duplicate header text in one sheet - fallback maps both columns, convert silently uses only the first (`_field_columns`' `field not in fields`).
- Risk: a `values` cell with comma-separated pairs ("G=Giriş, C=Çıkış") parses as one bogus pair with no note; the plan only requires `;`/newline handling.
- Risk: `config.SYNONYM_REWRITE`'s comment says "profile synonyms" but R3-9 says rule synonyms - could mislead the M10 worker.
- Bookkeeping: T77's commit message lacks the before/after test counts the task required (Run 2 final 2144 -> now 1956, ~150 of them new M7 tests).
- Missing tests: the two bug tests above (T110/T111); no CLI test for `--mapping` carrying stale disagreements.
