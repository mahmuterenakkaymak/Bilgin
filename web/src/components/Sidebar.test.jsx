import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
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

// ts alanını taşımak için historyItem'ın kopyası: sözleşme alanı olduğu gibi kalır.
function stamped(auditId, status, question, ts) {
  return { ...historyItem(auditId, status, question), ts };
}

// Saatler yerelden kuruluyor: "dün" takvimsel bir fark, makinenin saat diliminden bağımsız olmalı.
const NOON = new Date(2026, 9, 25, 12, 0, 0).getTime();
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;

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

  it("kayıtlı satır kendi created_at'ini taşır, zamansız kayıt zaman boşluğu kurmaz", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOON);
    const html = render({
      saved: [
        { id: 1, question: "İki dakika önceki kayıt", created_at: new Date(NOON - 2 * MINUTE).toISOString() },
        { id: 2, question: "Dünkü kayıt", created_at: "2026-10-24T06:00:00+00:00" },
        { id: 3, question: "Zamansız kayıt" },
        { id: 4, question: "Bozuk zamanlı kayıt", created_at: "2026-13-45" },
      ],
    });
    vi.useRealTimers();
    expect(html).toContain('<span class="side-time">2 dk önce</span>');
    expect(html).toContain('<span class="side-time">dün</span>');
    expect(html.match(/class="side-time"/g)).toHaveLength(2);
    expect(html).toContain("Zamansız kayıt");
    expect(html).not.toContain("undefined");
    expect(html).not.toContain("Invalid");
    expect(html.match(/aria-label="Kaydı sil"/g)).toHaveLength(4);
  });

  it("geçmiş satırı kısa Türkçe zamanını taşır, ts yoksa zaman yazılmaz", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOON);
    const html = render({
      history: [
        stamped("t1", "answered", "Dört dakika önceki soru", new Date(NOON - 4 * MINUTE).toISOString()),
        stamped("t2", "answered", "Üç saat önceki soru", new Date(NOON - 3 * HOUR).toISOString()),
        stamped("t3", "failed", "Dünkü soru", new Date(2026, 9, 24, 6, 0, 0).toISOString()),
        stamped("t4", "answered", "Beş gün önceki soru", new Date(2026, 9, 20, 6, 0, 0).toISOString()),
        stamped("t5", "answered", "Zamansız soru", ""),
        stamped("t6", "answered", "Bozuk ts", "2026-13-45"),
      ],
    });
    vi.useRealTimers();
    expect(html).toContain('<span class="side-time">4 dk önce</span>');
    expect(html).toContain('<span class="side-time">3 sa önce</span>');
    expect(html).toContain('<span class="side-time">dün</span>');
    expect(html).toContain('<span class="side-time">5 gün önce</span>');
    expect(html.match(/class="side-time"/g)).toHaveLength(4);
    expect(html).toContain("Zamansız soru");
    expect(html).not.toContain("undefined");
    expect(html).not.toContain("Invalid");
  });

  it("üst üste aynı soru ve durum tek satırda ×5 ile toplanır", () => {
    const five = ["e1", "e2", "e3", "e4", "e5"].map((id) => historyItem(id, "answered", "Depo bazında stok"));
    const html = render({
      history: [
        ...five,
        historyItem("e6", "failed", "Depo bazında stok"),
        historyItem("e7", "answered", "Net ciro"),
      ],
    });
    expect(html.match(/class="side-item"/g)).toHaveLength(3);
    expect(html).toContain('<span class="side-count">×5</span>');
    expect(html).toContain('title="Depo bazında stok"');
    // Farklı durum kendi satırı: ×2 diye erimez, tek başına sayı da taşımaz.
    expect(html).not.toContain("×2");
    expect(html.match(/class="side-count"/g)).toHaveLength(1);
    expect(html.match(/marker-err/g)).toHaveLength(1);
  });

  it("geçmişin tur sayısı KONUŞMALAR satırıyla aynı cümleyi yazar: '1 tur', 'tur 1' değil", () => {
    const html = render({
      history: [{ ...historyItem("u1", "answered", "İlk soru"), conversation_id: "kon-1", turn: 1 }],
    });
    expect(html).toContain('<span class="side-turn">1 tur</span>');
    expect(html).not.toContain("tur 1");
  });

  it("GEÇMİŞ listesi KONUŞMALAR gibi side-scroll ile kendi yüksekliğinde kayar", () => {
    const html = render({});
    expect(html).toContain('id="history-list" class="side-list side-scroll"');
    expect(html).toContain('id="conversation-list" class="side-list side-scroll"');
  });

  it("sadece boş sorular elenince iki boş cümle yine kurulur", () => {
    const html = render({
      history: [{ audit_id: "z1", question: "" }, { audit_id: "z2", question: "   ", status: "answered" }],
    });
    expect(html).toContain("Geçmiş boş.");
    expect(html).toContain("Henüz kayıtlı soru yok.");
    expect(html).not.toContain("side-count");
  });
});
