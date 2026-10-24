# Visual review — M17 (Run 5 web UI, `serve --llm fake`)

## Real problems
1. **Answer table · 390px** — the numbers are not on screen: the header is clipped mid-word (`SATIS_MIK`), 160/148/141/139 are missing and only the 2-char `11` survives. `.result-table` cells are `white-space: nowrap` inside an `overflow-x: auto` wrap, so the numeric column sits outside the viewport with no hint of a sideways scroll. The one thing this product sells is the number.
2. **Ambiguous question · both widths** — the `clarification-card` shot shows a plain answer and the flow's option click times out. `serve` without `--dataset` opens a session with `dataset=None`, so the fake gets an empty ambiguous list and answers A01 with the fallback product list: the clarification feature is dead in the README's no-model demo.
3. **Ask screen · 390px** — the page is 660px wide and scrolls sideways (the landing page is 390). `.ask-box` is a grid whose items keep `min-width: auto`, so one nowrap example chip sets a floor the whole page inherits: chips clipped mid-sentence, textarea and cards stretched. Reads as a broken build.
4. **Rules · 390px** — the `İşlem` column (Düzenle/Sil) is outside the visible box and rows run ~8 lines tall, so on a phone no rule can be edited or deleted at all.
5. **Chart** — it sits on the page background *below* the answer card (App.jsx:118 ASSUMPTION), with no title, no unit and x-labels only under bars 1/3/5; answer and chart don't read as one thing, and at 390 it is cut at the fold.
6. **Export** — `after-export` is pixel-identical to before it: the CSV/Excel clicks change nothing on screen, so nothing says the file arrived.
7. **History** — ~25 identical truncated rows, no time, no grouping; the newest feature looks broken even though every record carries `ts`.
8. **First load** — `/favicon.ico` 404s (index.html declares no icon): a console error on every visit and a blank tab.
9. **Evidence panel** — `run_sql` output is a pipe-smoke wall (`STK0013 | Kakaolu … | 160,00 STK0016 | …`) and `Mod rag` shows an internal label to end users.

## Craft ideas (cheap, clearly better)
10. One 150 ms entrance for card + chart, and a 2s `İndirildi ✓` state on the export buttons — the silent download becomes legible.
11. Relative time per history row (`4 dk önce`) plus collapsing consecutive repeats (`×7`): the sidebar reads as a log instead of a wall of clones.
12. A count badge on `Kayıtlılar ve geçmiş` — on a phone the drawer's contents are invisible behind the pill, so there is no hint of what is in there.
