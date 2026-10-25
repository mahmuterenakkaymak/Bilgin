// T241 (R6-19): yönetici olmayan kullanıcı kuralları yalnız okur. Ekran aynı liste, aynı bant;
// içinde tek bir yazma düğmesi yoktur. SSR çıktısı aranır — olay yok, işaret yok.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import RulesScreen from "./RulesScreen.jsx";

const noop = () => {};

// Cümlelerdeki kesme işareti ve tırnak SSR çıktısında düz karakter değildir; okunur metin öyle aranır.
function render(element) {
  return renderToStaticMarkup(element)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&");
}

const screen = (props) => render(<RulesScreen onRefresh={noop} {...props} />);

const RULES = [
  {
    id: "net_satis",
    term: "Net satış",
    synonyms: ["net satış"],
    definition: "Satıştan iadelerin düşüldüğü hal.",
    sql_hint: "SUM(...)",
    tables: ["TBLSTHAR"],
    markers: [],
  },
];

const TABLES = ["TBLSTHAR", "TBLFATUIRS"];

const STALE = { fresh: false, reason: "Kuralların içeriği değişti." };

describe("RulesScreen — salt-okur küme", () => {
  it("bant cümlesini taşır; hiçbir yazma düğmesi kurmaz", () => {
    const html = screen({ rules: RULES, index: { fresh: true }, tables: TABLES, readOnly: true });
    expect(html).toContain('id="rules-readonly-note"');
    expect(html).toContain("İş kurallarını yalnız yönetici değiştirebilir.");
    expect(html).not.toContain('id="rule-add"');
    expect(html).not.toContain('id="rule-form"');
    expect(html).not.toContain(">Düzenle</button>");
    expect(html).not.toContain(">Sil</button>");
    expect(html).not.toContain("Silinsin mi?");
  });

  it("liste yine okunur: terim ve satırlar yerinde, İşlem sütunu kalkar", () => {
    const html = screen({ rules: RULES, index: { fresh: true }, tables: TABLES, readOnly: true });
    expect(html).toContain("Net satış");
    expect(html).toContain('id="rules-screen"');
    expect(html).not.toContain(">İşlem</th>");
  });

  it("bayatlık bandının sözü kalır, yeniden kurma düğmesi gelmez", () => {
    const html = screen({ rules: RULES, index: STALE, tables: TABLES, readOnly: true });
    expect(html).toContain('id="index-stale"');
    expect(html).toContain("Kurallar değişti, indeks eski.");
    expect(html).not.toContain('id="index-rebuild"');
  });

  it("boş küme yönetici düğmesine gönderme yapmaz", () => {
    const html = screen({ rules: [], index: { fresh: true }, tables: TABLES, readOnly: true });
    expect(html).toContain("Henüz kural yok.");
    expect(html).not.toContain("ile ekleyin");
  });
});

describe("RulesScreen — yönetici ve tek kullanıcı aynı kalır", () => {
  it("readOnly yokken tüm yazma düğmeleri ve İşlem sütunu durur", () => {
    const html = screen({ rules: RULES, index: STALE, tables: TABLES });
    expect(html).not.toContain('id="rules-readonly-note"');
    expect(html).toContain('id="rule-add"');
    expect(html).toContain(">Düzenle</button>");
    expect(html).toContain(">Sil</button>");
    expect(html).toContain(">İşlem</th>");
    expect(html).toContain('id="index-rebuild"');
  });
});
