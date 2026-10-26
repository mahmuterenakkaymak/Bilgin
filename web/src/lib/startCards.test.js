import { describe, expect, it } from "vitest";
import {
  BUSINESS_ROLES,
  EVERY_ROLE_LABEL,
  PERSONAL_ROLE_LABEL,
  cardValueText,
  groupByRole,
  refreshedText,
  roleLabel,
  suggestDisplay,
} from "./startCards.js";

const NOW = new Date("2026-10-26T09:00:00Z");
const ago = (seconds) => new Date(NOW.getTime() - seconds * 1000).toISOString();

describe("refreshedText", () => {
  it("bir dakikadan yeni kart 'az önce' der", () => {
    expect(refreshedText(ago(0), NOW)).toBe("az önce");
    expect(refreshedText(ago(59), NOW)).toBe("az önce");
  });

  it("dakika ve saat dilimleri ayrı ayrı okunur", () => {
    expect(refreshedText(ago(60), NOW)).toBe("1 dk önce");
    expect(refreshedText(ago(5 * 60 + 40), NOW)).toBe("5 dk önce");
    expect(refreshedText(ago(59 * 60), NOW)).toBe("59 dk önce");
    expect(refreshedText(ago(60 * 60), NOW)).toBe("1 sa önce");
    expect(refreshedText(ago(3 * 3600 + 20 * 60), NOW)).toBe("3 sa önce");
  });

  it("saat dilimli etiket okunur, ileri tarihli kart 'az önce' sayılır", () => {
    expect(refreshedText("2026-10-26T11:58:00+03:00", "2026-10-26T09:00:00Z")).toBe("2 dk önce");
    expect(refreshedText(ago(-120), NOW)).toBe("az önce");
  });

  it("tarih yoksa ya da bozuksa cümle boş kalır", () => {
    for (const value of [null, undefined, "", "dün", Number.NaN]) {
      expect(refreshedText(value, NOW)).toBe("");
    }
    expect(refreshedText(ago(600), new Date(Number.NaN))).toBe("");
  });
});

describe("cardValueText", () => {
  it("sayı kartının değeri Türkçe okunur", () => {
    expect(cardValueText({ display: "number", value: 1234.5 })).toBe("1.234,5");
    expect(cardValueText({ display: "number", value: 42 })).toBe("42");
  });

  it("değer yoksa '–' gösterilir, hiçbir şey göstermemezlik değil", () => {
    expect(cardValueText({ display: "number", value: null })).toBe("–");
    expect(cardValueText({ display: "number" })).toBe("–");
  });

  it("grafiğin, tablonun ve hata kartının büyük değeri yoktur", () => {
    expect(cardValueText({ display: "chart", chart: {} })).toBe("");
    expect(cardValueText({ display: "table", columns: ["A"], rows: [[1]] })).toBe("");
    expect(cardValueText({ display: "number", error: "İzin verilmeyen kolon." })).toBe("");
    expect(cardValueText(undefined)).toBe("");
  });
});

describe("groupByRole", () => {
  const rows = [
    { id: 7, business_role: null },
    { id: 1, business_role: "muhasebe" },
    { id: 2, business_role: "satis" },
    { id: 3, business_role: "*" },
    { id: 4, business_role: "satis" },
    { id: 5, business_role: "genel" },
    { id: 6, business_role: "satin_alma" },
  ];

  it("gruplar BUSINESS_ROLES sırasıyla gelir, sonra Herkes ve Kişisel", () => {
    expect(groupByRole(rows).map((group) => [group.role, group.label, group.items.map((r) => r.id)])).toEqual([
      ["satis", "Satış", [2, 4]],
      ["satin_alma", "Satın alma", [6]],
      ["muhasebe", "Muhasebe", [1]],
      ["genel", "Genel", [5]],
      ["*", EVERY_ROLE_LABEL, [3]],
      ["", PERSONAL_ROLE_LABEL, [7]],
    ]);
  });

  it("hiç soru olmayan rol grup olarak dönmez", () => {
    expect(groupByRole([{ id: 1, business_role: "yonetim" }])).toEqual([
      { role: "yonetim", label: "Yönetim", items: [{ id: 1, business_role: "yonetim" }] },
    ]);
    expect(groupByRole([])).toEqual([]);
  });

  it("tanınmayan rol sona kendi koduyla eklenir, satır kaybolmaz", () => {
    const [first, last] = groupByRole([
      { id: 1, business_role: "depo" },
      { id: 2, business_role: "satis" },
    ]);
    expect([first.role, last.role, last.label]).toEqual(["satis", "depo", "depo"]);
  });

  it("liste olmayan giri boş grup demetidir", () => {
    expect(groupByRole(undefined)).toEqual([]);
    expect(groupByRole(null)).toEqual([]);
  });
});

describe("roleLabel ve roller", () => {
  it("rol kodları config.BUSINESS_ROLES ile aynı sırada", () => {
    expect(BUSINESS_ROLES.map((item) => item.role)).toEqual([
      "satis",
      "satin_alma",
      "muhasebe",
      "yonetim",
      "genel",
    ]);
  });

  it("özel değerlerin etiketi vardır, rol kodu kendi etiketini taşır", () => {
    expect(roleLabel("*")).toBe(EVERY_ROLE_LABEL);
    expect(roleLabel(null)).toBe(PERSONAL_ROLE_LABEL);
    expect(roleLabel("muhasebe")).toBe("Muhasebe");
    expect(roleLabel("depo")).toBe("depo");
  });
});

describe("suggestDisplay", () => {
  it("1x1 sayı number, grafiği olan chart, ötekiler table", () => {
    expect(suggestDisplay({ columns: ["SATIS"], rows: [[1200.5]], chart: null })).toBe("number");
    expect(suggestDisplay({ columns: ["AY", "SATIS"], rows: [["Eylül", 12]], chart: { kind: "bar" } })).toBe("chart");
    expect(suggestDisplay({ columns: ["AD"], rows: [["Ankara"]], chart: null })).toBe("table");
    expect(suggestDisplay({ columns: ["A", "B"], rows: [[1, 2]], chart: null })).toBe("table");
  });

  it("sayı hem sayıya hem grafiğe uygunsa number önerilir (Python ile aynı sıra)", () => {
    expect(suggestDisplay({ columns: ["SATIS"], rows: [[1200.5]], chart: { kind: "line" } })).toBe("number");
  });

  it("alanlar eksikse table: NaN/undefined yerine bilinen bir seçenek", () => {
    expect(suggestDisplay()).toBe("table");
    expect(suggestDisplay({})).toBe("table");
    expect(suggestDisplay({ columns: ["SATIS"], rows: [[null]], chart: null })).toBe("table");
    expect(suggestDisplay({ columns: ["SATIS"], rows: [], chart: undefined })).toBe("table");
  });
});
