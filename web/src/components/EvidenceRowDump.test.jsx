// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import Evidence from "./Evidence.jsx";

// run_sql/submit_sql adımının özeti modelin bir sonraki turu için yazılmış satır dökümüdür
// (tools.py `_answer`): kolon satırı, " | " ile ayrılmış hücreler, satır sayısı. Kart tabloyu zaten
// gösterdiği için panel bunu sayıya çevirir; hata satırı ise olduğu gibi okunur.
const ROW_DUMP = "Kolonlar: A, B a | 1 | b | 2 | c | 3";

function panel(payload) {
  const html = renderToStaticMarkup(<Evidence payload={payload} />)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&");
  const start = html.indexOf('id="evidence"');
  expect(start).toBeGreaterThan(-1);
  return html.slice(start);
}

describe("kanıtta satır dökümü", () => {
  it("satır dökümü sayıya döner: ' | ' koşusu kalmaz, satır sayısı okunur", () => {
    const body = panel({
      status: "answered",
      sql: "SELECT a, b FROM T",
      steps: [{ tool: "run_sql", ok: true, summary: ROW_DUMP }],
    });
    expect(body).not.toContain(" | ");
    expect(body).toContain("satır");
  });

  it("başarısız adımın özeti olduğu gibi kalır", () => {
    const body = panel({
      status: "failed",
      sql: "SELECT a, b FROM T",
      steps: [{ tool: "run_sql", ok: false, summary: ROW_DUMP }],
    });
    expect(body).toContain(ROW_DUMP);
  });

  it("panel yalnız kartın çip almadığı olguları listeler: çiptekiler yinelenmez", () => {
    const body = panel({
      status: "answered",
      sql: "SELECT a, b FROM T",
      facts: [
        { name: "total", label: "Toplam", display: "8.910" },
        { name: "mean", label: "Ortalama", display: "1.782,00" },
        { name: "min", label: "En düşük", display: "1.105" },
      ],
    });
    expect(body).toContain('<span class="fact-label">En düşük</span><span class="fact-value">1.105</span>');
    expect(body).not.toContain('<span class="fact-label">Toplam</span>');
    expect(body).not.toContain('<span class="fact-label">Ortalama</span>');
  });
});
