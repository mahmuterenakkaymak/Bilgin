# REVIEW M4 (T31-T46)

Base e90b62e (Run 2 plan) -> HEAD acbf4ea. Full suite and smoke pass. Run 1 lines of golden.jsonl unchanged apart from the new fields; Run 1 pin holds; Q01-Q40 equal their references on seed 42 (no empty answer).

- **BUG (T67)**: schema.json `TBLSTHAR_ARSIV.description` says "2026 hareketleri burada, 2025 hareketleri TBLSTHAR'da yoktur" - it claims the archive holds 2026 movements. The text goes into every `full` / `get_table_details` answer and contradicts R2-3 (archive = 2025 only), so the A/B would partly measure a typo.
- **BUG (T68)**: rules `doviz_tl` and `teslim_bekleyen` have `markers: []` although Q23/Q26/Q36/Q38 cite them; R2-11 (markers must match every citing golden SQL) is vacuous for them, and the ASSUMPTION in rules.py ("empty only for rules no question cites yet") is wrong.
- **BUG (T69)**: `extra.DISTRACTOR_ROWS` default 0 still gives every filler distractor 1 row (`1 + randint(0, min(N, 4))`), 62 tables; R2-4/T39 say 0-5 rows with default 0, the config comment says "0 = stays schema-only", and build-db's "şema-yalnız Y" is always 0. tests/test_build_world.py::test_other_distractors_get_a_single_filler_row_by_default encodes it.
- **BUG (T70)**: `_stok_fiyat` draws random dates, so a product can get two S rows with the same GECERLILIK_TARIHI (seeds 3, 10, 12, 16, 23, 28, 33 of 1-40; not 42). "Liste fiyatı = latest date" is then ambiguous and Q15's golden SQL returns the product twice.
- ASSUMPTIONs checked OK: config Run 2 paths, doc.table_detail hides distractors in the unknown-table hint, extra._fill (empty table on a foreign schema), test_golden_contract needs_values, test_schema_doc allowlist = every table.
- Risk: golden Q03 ("Geçen ay"), Q05 (net satış), Q09 (teslim tarihi yok) use a rule's concept without listing it, so needs_rule/retrieval metrics under-count those rules.
- Risk: `sql_hint` of ciro/net_satis/iade_orani is nearly the golden SQL; R2-16 only checks questions, so `full_rules` and `rag` get an easier job than the model would in a real ERP.
- Risk: TBLMUHFIS books purchase KDV on 391 (hesaplanan) for every invoice; no golden test shows that the near-duplicate named in a `distractor` question's note gives a different answer (test_build_world checks it only for TBLSTHAR_LOG and TBLCASABIT_YEDEK).
- Risk: report/table still prints int codes with thousand dots (open since M3); eval/REVIEW.md previews inherit it.
- Missing tests: any seed other than 42 for the golden answers; every rule has a non-empty marker; distractor tag vs. near-duplicate difference per question.
