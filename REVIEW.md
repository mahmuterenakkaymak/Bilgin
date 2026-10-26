# REVIEW M22 (T296-T303 + M21 review fixes T353-T355; range 0a1aa84^ -> 69a4f49)

Whole-project checks pass (17 commands). Compared against PLAN R7-10..R7-14 and Contracts "chart_spec (ext.)", "followup chain", "ContextNote", "TurnSummary". Visual-review findings are already T356-T362.

- **BUG (T363)**: `ambiguous_entity` never matches ASCII column names. `_loose` uses `index.text.fold`, which keeps ü/ş/ç, so aliases "müşteri"/"ürün"/"tedarikçi" miss MUSTERI_ID / URUN_ADI / TEDARIKCI_ADI (the wwi_real style); only CARI_KOD, STOK_*, FATURA_* work (reproduced).
- **BUG (T364)**: false positives - "Bu ay hangi ürün en çok satıldı?", "Bu yıl müşteri sayısı?", plural "Bu carilerin ..." / "Bu müşterilerin hepsi" all ask "Hangi müşteriyi kastediyorsunuz?" (any bu/şu/o + any prefix match; R7-12 says singular demonstrative). The tests only pin "Bunlara" and "Bu müşteriye".
- **BUG (T365)**: `_chosen` splits the option at the first " (", so a value holding one (every WWI customer name) becomes a prefix, fails `validate_note` and the evidence line silently disappears for the entity the user chose.
- ASSUMPTIONs checked and holding: loop hint lines (followup_hints + refine_hint), forced-chart fallback `{"type": None, "option": None, "reason"}` (ChartView draws nothing, answer_text carries the reason), `_chain_note` refines_sql_of, GET conversation dataset filter (NULL dataset skips the filter), `--followups` default dataset.
- Contracts traced: chart-only payload keys equal the normal path's (`_execute` fills tables_used/rules_used/masked/warnings; no agent, no narrator); `chart_kind` in the summary reads `type` (None when only a reason); eval followups report keys match report.py/CLI lines; Dataset.followups defaults match "followup chain".
- Risk: `clarification` now carries a `column` key (stored, sent to the UI); Contracts list only {question, options}. Harmless today, a strict schema test would flag it.
- Risk: `_chain_note` sets refines_sql_of only for a turn tagged "refine", but no synthetic/wwi chain uses that tag (they use filter/period/top/set), so fake notes never carry it; eval compares uses_turns only, so nothing notices.
- Risk: the first, standalone question ignores a chart wish ("aylık cirosu çizgi grafikte") - only a follow-up chart-only turn forces the kind; `eval --compare --followups` silently ignores `--followups`; `Dataset.followups()` KeyErrors on a chain line without "turns".
- Risk: the screen `ask --conversation` still skips chart_only/ambiguous_entity (documented), so CLI and web differ.
- Missing tests: ambiguity on ASCII/plural/"Bu ay" inputs, option values containing " (", and an eval chain whose turn is answered by a clarification (the runner never supplies a choice, so such a turn is scored wrong).
