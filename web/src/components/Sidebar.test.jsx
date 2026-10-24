import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import Sidebar from "./Sidebar.jsx";

const noop = () => {};

// Cümlelerdeki kesme işareti ve tırnak SSR çıktısında düz karakter değildir; okunur metin öyle aranır.
function render(props) {
  return renderToStaticMarkup(<Sidebar onAsk={noop} onRemoved={noop} {...props} />)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&");
}

const SAVED = [
  {
    id: 7,
    question: "Eylül 2026'da net satışımız ne kadar?",
    mode: "full_rules",
    sql: "SELECT 1",
    dataset: "synthetic_erp",
    created_at: "2026-10-25T09:12:00+00:00",
  },
  { id: 6, question: "En çok satan 5 ürün", mode: null, sql: null, dataset: "synthetic_erp", created_at: "2026-10-24T18:03:00+00:00" },
];

function historyItem(auditId, status, question) {
  return {
    ts: "2026-10-25T09:00:00.000+00:00",
    audit_id: auditId,
    dataset: "synthetic_erp",
    mode: "full_rules",
    question,
    choice: null,
    status,
    sql: "SELECT 1",
    row_count: 3,
    error: null,
  };
}

describe("Sidebar", () => {
  it("boş kenar çubuğu iki boş cümleyi kendi listelerinde gösterir", () => {
    const html = render({});
    expect(html).toContain('id="saved-list"');
    expect(html).toContain('id="history-list"');
    expect(html).toContain("Henüz kayıtlı soru yok.");
    expect(html).toContain("Geçmiş boş.");
    expect(html).toContain(">Kayıtlı sorular</h2>");
    expect(html).toContain(">Geçmiş</h2>");
  });

  it("liste alanları hiç gelmese de boş haller kurulur", () => {
    const html = render({ saved: null, history: undefined });
    expect(html).toContain("Henüz kayıtlı soru yok.");
    expect(html).toContain("Geçmiş boş.");
  });

  it("kayıtlı satır soruyu yeniden sorar ve × ile silinir", () => {
    const html = render({ saved: SAVED });
    expect(html).toContain('id="saved-list"');
    expect(html).toContain("Eylül 2026'da net satışımız ne kadar?");
    expect(html).toContain("En çok satan 5 ürün");
    expect(html.match(/aria-label="Kaydı sil"/g)).toHaveLength(2);
    expect(html.match(/>×<\/button>/g)).toHaveLength(2);
  });

  it("geçmiş durumunu ✓ / ? / ✗ ile okunur kılar", () => {
    const html = render({
      history: [
        historyItem("a1", "answered", "Geçen ay net ciro"),
        historyItem("a2", "needs_clarification", "En çok satan ürün hangisi?"),
        historyItem("a3", "failed", "Depo bazında stok"),
        historyItem("a4", "llm_error", "Plasiyer başına ciro"),
      ],
    });
    expect(html).toContain('<span class="side-marker marker-ok" aria-hidden="true">✓</span>');
    expect(html).toContain('<span class="side-marker marker-warn" aria-hidden="true">?</span>');
    expect(html).toContain('<span class="side-marker marker-err" aria-hidden="true">✗</span>');
    expect(html.match(/marker-err/g)).toHaveLength(2);
    expect(html).toContain("En çok satan ürün hangisi?");
  });

  it("geçmiş üreticinin sırasıyla yazılır, kayıtlılar kendi sırasında kalır", () => {
    const html = render({
      saved: SAVED,
      history: [historyItem("b1", "answered", "İlk soru"), historyItem("b2", "answered", "İkinci soru")],
    });
    expect(html.indexOf("İlk soru")).toBeLessThan(html.indexOf("İkinci soru"));
    expect(html.indexOf("Eylül 2026'da net satışımız ne kadar?")).toBeLessThan(html.indexOf("En çok satan 5 ürün"));
  });

  it("soru metni olmayan satır kurulmaz, eksik durum ✗ okunur", () => {
    const html = render({
      saved: [{ id: 1, question: "   " }, { id: 2 }, { question: "idsiz kayıt" }],
      history: [{ audit_id: "c1", question: "Durumsuz soru" }, { audit_id: "c2", question: "" }, {}],
    });
    expect(html).toContain("Durumsuz soru");
    expect(html).toContain('<span class="side-marker marker-err" aria-hidden="true">✗</span>');
    expect(html).toContain("Henüz kayıtlı soru yok.");
    expect(html).not.toContain("idsiz kayıt");
    expect(html).not.toContain("undefined");
    expect(html.match(/id="history-list"/g)).toHaveLength(1);
  });
});
