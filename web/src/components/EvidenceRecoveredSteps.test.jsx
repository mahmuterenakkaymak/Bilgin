import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import Evidence from "./Evidence.jsx";

// Red satırı nl2sql/agent/tools.py `_unknown`'ın döndürdüğü metindir: araç listesi modelin bir
// sonraki turuna yazılmıştır, kanıt panelini okuyan iş kullanıcıya değil.
const UNKNOWN_TOOL =
  "Bilinmeyen araç: get_schema. Kullanabileceklerin: search_schema, get_table_details, find_join_path, " +
  "search_rules, sample_values, run_sql, submit_sql, ask_clarification.";

const STEPS = [
  { tool: "search_schema", ok: true, summary: "Kolonlar: STOK_KODU, STOK_ADI. 5 satır." },
  { tool: "get_schema", ok: false, summary: UNKNOWN_TOOL },
  { tool: "submit_sql", ok: true, summary: "Sorgu cevap olarak alındı ve çalıştırıldı." },
];

function panel(status) {
  const payload = { status, sql: "SELECT 1", steps: STEPS, tables_used: ["TBLSTHAR"] };
  return renderToStaticMarkup(<Evidence payload={payload} />)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&");
}

describe("cevabı bulunan kanıtta kendini toparlayan adım", () => {
  it("başarısız adım nötr satırdır: çarpı yok, adım yine okunur", () => {
    const html = panel("answered");
    expect(html).not.toContain("step-failed");
    expect(html).not.toContain("✗");
    expect(html).toContain('class="step-tool">get_schema</span>');
    expect(html).toContain("Bilinmeyen araç: get_schema.");
    expect(html).toContain(">✓</span>");
  });

  it("araç sözlüğü panelin hiçbir yerinde okunmaz", () => {
    const html = panel("answered");
    expect(html).not.toContain("Kullanıcıların");
    expect(html).not.toContain("Kullanabileceklerin");
    expect(html).not.toContain("search_schema, get_table_details");
  });

  it("cevabı olmayan yanıtta aynı adım işaretini korur", () => {
    const html = panel("failed");
    expect(html).toContain('class="step step-failed"');
    expect(html).toContain(">✗</span>");
  });
});
