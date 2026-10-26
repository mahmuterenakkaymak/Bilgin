// Raporun altı karesi tek liste ve tek stil: "Kişisel veri 1" — bir şablon sorgulanabilir bir
// kümeye dönüşmeden önce bir ERP yöneticisini durdurması gereken sayı — "Referans 0" ile görsel
// olarak aynı okunuyordu. Kare kehribara dönünce sayı ayrılıyor; Kapalı ve Referans'ın ne saydığı
// ise karelerin altındaki tek satırda duruyor.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import MapScreen from "./MapScreen.jsx";
import { initialMapState, mapReducer } from "../lib/mapFlow.js";

// Denetim raporu yalnız `previewed` halinde kuruluyor; hâl gerçek geçişten indirgeniyor.
function report(overrides = {}) {
  const state = [
    { type: "select", filename: "harita.xlsx" },
    { type: "preview" },
    {
      type: "previewed",
      preview: {
        preview_id: "p-1",
        dataset: { name: "ornek_fatura", display_name: "Örnek Fatura", connection: "sqlite" },
        counts: { tables: 3, columns: 24, pii: 0, deny: 0, references: 0, rules: 4, ...overrides },
        errors: [],
        warnings: [],
        db_check: { checked: false, missing_in_db: [], only_in_db: [], message: null },
      },
    },
  ].reduce((current, action) => mapReducer(current, action), initialMapState);

  return renderToStaticMarkup(<MapScreen state={state} />)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&");
}

// Karenin kendi açılış etiketi: etiketten geriye ilk div, o karenin div'idir.
function tile(html, label) {
  const open = html.indexOf(`>${label}</dt>`);
  if (open < 0) return "";
  const start = html.lastIndexOf("<div", open);
  return html.slice(start, html.indexOf("<dt", start));
}

describe("harita raporu — kişisel verinin uyarı tonu", () => {
  it("bir kişisel veri kolonu kareyi uyarıya çevirir, diğer kareler düz kalır", () => {
    const html = report({ pii: 1 });
    expect(tile(html, "Kişisel veri")).toContain('class="map-stat is-warn"');
    expect(tile(html, "Tablo")).toBe('<div class="map-stat">');
    expect(tile(html, "Kapalı")).toBe('<div class="map-stat">');
    expect(tile(html, "Referans")).toBe('<div class="map-stat">');
    expect(html).toContain(">Kişisel veri</dt><dd>1</dd>");
  });

  it("kişisel veri sıfırsa hiçbir kare uyarı tonu taşımaz", () => {
    const html = report({ pii: 0 });
    expect(html).not.toContain("is-warn");
    expect(tile(html, "Kişisel veri")).toBe('<div class="map-stat">');
  });

  it("Kapalı ve Referans'ın ne saydığı karelerin altında tek satır yazılıdır", () => {
    const html = report({ pii: 1 });
    expect(html).toContain('id="map-stats-note"');
    expect(html).toContain("Kapalı: modelin hiçbir metnine düşmeyen kolonlar");
    expect(html).toContain("Referans: bir kolonun hangi tabloya bağlandığını söyler");
  });
});
