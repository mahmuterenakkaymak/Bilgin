// @vitest-environment jsdom
// R8-18: cevap kartının kendi kabarı iki dilde — durum satırı, eyleme düğmeleri, tablonun alt
// yazısı, kanıt başlıkları ve netleştirme kartı. İki dil aynı id kümesini boyamalı; İngilizce
// çıktının kabarı Türkçe harf taşımamalı; Türkçe çıktı bugünkü cümleleri harfi harfine vermeli —
// AnswerCard.test.jsx, AnswerCardExportCount.test.jsx, ReadyQuestionForm.test.jsx,
// EvidenceFacts.test.jsx ve ChartClarify.test.jsx o cümleleri bekliyor. Sunucunun yazdığı her şey
// (cevap cümlesi, adım özetleri, olgu etiketleri, bağlam satırı) ve verinin kendisi çevrilmez;
// sayı ise arayüzün diliyle okunur (R8-3).
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import answered from "../fixtures/answered.json";
import clarification from "../fixtures/clarification.json";
import { I18nProvider } from "../i18n/index.js";
import * as api from "../lib/api.js";
import AnswerCard from "./AnswerCard.jsx";
import ChartView from "./ChartView.jsx";
import ClarificationCard from "./ClarificationCard.jsx";
import Evidence from "./Evidence.jsx";

// Pano ve yeniden onay istekleri ağa çıkmaz; düğmenin aşama yazısı okunur.
vi.mock("../lib/api.js", async (importOriginal) => ({
  ...(await importOriginal()),
  pinCard: vi.fn(),
  readyUpdate: vi.fn(),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const noop = () => {};
const TURKISH = /[çğıöşüÇĞİÖŞÜ]/;

// Türkçe cevap: sunucunun okunuşu tr, basamakları da tr'dir.
const TR = answered;

// İngilizce cevap: aynı turun sunucudaki hali — etiketler, cümleler ve sayı okunuşları en.
const EN = {
  ...answered,
  question: "Which five products sold the most in September 2026?",
  answer_lang: "en",
  answer_text: "The best-selling product in September 2026 was Black Tea 500 g with 2,480 units.",
  facts: [
    { name: "row_count", label: "Row count", column: null, value: 5, display: "5", percent: false },
    { name: "total", label: "Total", column: "SATIS_MIKTARI", value: 8910, display: "8,910", percent: false },
    {
      name: "max",
      label: "Highest (Black Tea 500 g)",
      column: "SATIS_MIKTARI",
      value: 2480,
      display: "2,480",
      percent: false,
    },
    { name: "min", label: "Lowest", column: "SATIS_MIKTARI", value: 1105, display: "1,105", percent: false },
    { name: "mean", label: "Average", column: "SATIS_MIKTARI", value: 1782, display: "1,782.00", percent: false },
    {
      name: "top_item",
      label: "Top item",
      column: "SATIS_MIKTARI",
      value: "Black Tea 500 g",
      display: "Black Tea 500 g",
      percent: false,
    },
    { name: "top_share", label: "Top share", column: "SATIS_MIKTARI", value: 27.8, display: "27.8%", percent: true },
  ],
  rows: [
    ["STK0012", "Black Tea 500 g", 2480],
    ["STK0003", "Wheat Flour 500 g", 2140],
    ["STK0007", "Olive Oil 1 L", 1725],
    ["STK0021", "Sugar 5 kg", 1460],
    ["STK0005", "Bulgur 1 kg", 1105],
  ],
  steps: [
    { tool: "get_schema", ok: true, summary: "Read the columns of TBLSTHAR and TBLSTSABIT." },
    { tool: "run_sql", ok: true, summary: "Columns: STOK_KODU, STOK_ADI, SATIS_MIKTARI. 5 rows." },
    { tool: "submit_sql", ok: true, summary: "The query was accepted." },
  ],
};

const PAYLOAD = { tr: TR, en: EN };

// Cümlelerdeki kesme işareti ve tırnak SSR çıktısında düz karakter değildir; okunur metin öyle aranır.
function render(element) {
  return renderToStaticMarkup(element)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&");
}

const inLang = (lang, element) => render(<I18nProvider lang={lang}>{element}</I18nProvider>);
const ids = (html) => [...html.matchAll(/id="([^"]+)"/g)].map((match) => match[1]).sort();

// Kartın iki dili aynı yüklerle: yönetici iki dilde de aynı, yoksa id kümesi değil dil sınanırdı.
const card = (lang, payload = PAYLOAD[lang], props = {}) =>
  inLang(lang, <AnswerCard payload={payload} onSave={noop} isAdmin {...props} />);
const panel = (lang, payload = PAYLOAD[lang]) => inLang(lang, <Evidence payload={payload} />);
const clarify = (lang) => inLang(lang, <ClarificationCard payload={clarification} onChoose={noop} onChange={noop} />);

// Kesik sonuç: sekiz satır ekranda, toplamı sunucu söylüyor.
function cutRows(lang) {
  const rows = Array.from({ length: 8 }, (_, index) => [`FTH${index}`, index + 1]);
  return { ...PAYLOAD[lang], columns: ["FISNO", "ADET"], rows, row_count: 1234, truncated: true };
}

let container;
let root;

async function mount(node) {
  container = document.createElement("div");
  document.body.append(container);
  // İndirme bir <a>: jsdom gezinmeyi uygular ve bağırır; tıklama yalnız adı okunduğu için engellenir.
  container.addEventListener("click", (event) => {
    if (event.target.closest("a")) event.preventDefault();
  });
  root = createRoot(container);
  await act(async () => root.render(node));
  return container;
}

function unmount() {
  act(() => root.unmount());
  container.remove();
  container = undefined;
  root = undefined;
}

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function click(node) {
  await act(async () => node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })));
  await settle();
}

// jsdom'ın panosu yoktur: kopyalama düğmesinin "kopyalandı" hali kendi sahte panosuyla okunur.
function fakeClipboard() {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: () => Promise.resolve() },
  });
}

afterEach(() => {
  if (root) unmount();
  delete navigator.clipboard;
});

describe("cevap kartı iki dilde", () => {
  it("aynı id kümesini boyar: çeviri markup'ı değiştirmez", () => {
    const tr = ids(card("tr"));
    for (const id of ["answer-card", "answer-text", "result-table", "export-csv", "save-question", "evidence"]) {
      expect(tr).toContain(id);
    }
    expect(ids(card("en"))).toEqual(tr);
    expect(ids(clarify("en"))).toEqual(ids(clarify("tr")));
    expect(ids(panel("en"))).toEqual(ids(panel("tr")));
  });

  it("İngilizce kartın kabarı Türkçe harf ve bugünün cümlesini taşımıyor", () => {
    const html = card("en");
    expect(html).not.toMatch(TURKISH);
    for (const text of [
      "✓ Answered · full_rules · 8.3 s",
      ">Save the question</button>",
      ">Add to my board</button>",
      ">Make a ready question</button>",
      "Download all:",
    ]) {
      expect(html).toContain(text);
    }
    for (const text of ["✓ Cevaplandı", ">Soruyu kaydet<", ">Panoma ekle<", ">Hazır soru yap<", "Tamamını indir:"]) {
      expect(html).not.toContain(text);
    }
  });

  it("Türkçe kart bugünkü cümleleri harfi harfine veriyor ve provider'sız haliyle aynı", () => {
    const html = card("tr");
    for (const text of [
      "✓ Cevaplandı · full_rules · 8,3 sn",
      ">Soruyu kaydet</button>",
      ">Panoma ekle</button>",
      ">Hazır soru yap</button>",
      "Tamamını indir:",
      '<span class="fact-value">8.910</span>',
      "<td class=\"num\">2.480</td>",
    ]) {
      expect(html).toContain(text);
    }
    expect(render(<AnswerCard payload={TR} onSave={noop} isAdmin />)).toBe(html);
  });

  it("seçilen anlam ve bağlam satırı: etiket kataloğun, sunucunun cümlesi olduğu gibi", () => {
    const choice = { tr: "Net satış (KDV hariç)", en: "Net sales (excluding VAT)" };
    for (const lang of ["tr", "en"]) {
      const html = card(lang, undefined, { choice: choice[lang] });
      expect(html).toContain(lang === "tr" ? `Anlam: ${choice.tr}` : `Meaning: ${choice.en}`);
    }
    // Bağlam satırının ön eki sunucuda cevabın diliyle yazılmıştır (context.evidence.prefix).
    const line = "Önceki turdan: Ürün adı Siyah Çay 500 g";
    const html = card("en", { ...EN, context: { line } });
    expect(html).toContain(`id="context-line" class="context-line">${line}</p>`);
  });

  it("sayılar arayüzün diliyle okunur: Türkçe cevap İngilizce arayüzde yeniden yazılır", () => {
    const en = card("en");
    expect(en).toContain('<td class="num">2,480</td>');
    expect(en).toContain('<span class="fact-value">1,782.00</span>');
    expect(card("en", cutRows("en"))).toContain("Showing the first 8 rows (of 1,234 total).");
    // Cevabın dili tr ise sunucunun okunuşu İngilizce arayüzün biçimine çevrilir.
    const cross = card("en", TR);
    expect(cross).toContain('<span class="fact-value">8,910</span>');
    expect(cross).toContain('<span class="fact-value">1,782.00</span>');
    expect(cross).toContain(">27.8%</span>");
    expect(card("tr", cutRows("tr"))).toContain("İlk 8 satır gösteriliyor (toplam 1.234).");
  });

  it("Türkçe cevap cümlesi İngilizce arayüzde çevrilmez", () => {
    const html = card("en", TR);
    expect(html).toContain(
      '<p id="answer-text" class="answer-text">Eylül 2026\'da en çok satan ürün 2.480 adetle Siyah Çay 500 g oldu',
    );
  });

  it("boş sonuç iki dilde de cümledir ve tablo kurmaz", () => {
    const empty = { ...EN, rows: [], row_count: 0 };
    expect(card("en", empty)).toContain(">No records match this question.</p>");
    expect(card("en", empty)).not.toContain('id="result-table"');
    expect(card("tr", { ...TR, rows: [], row_count: 0 })).toContain(">Bu soruya uyan kayıt yok.</p>");
  });
});

describe("kanıt paneli iki dilde", () => {
  it("başlıklar, kopyalama düğmesi ve süre satırı çevrili", () => {
    const en = panel("en");
    for (const text of [
      "How I worked it out",
      ">Copy</button>",
      "<dt>Mode</dt><dd>full_rules</dd>",
      "<dt>Tables</dt><dd>TBLSTHAR, TBLSTSABIT</dd>",
      "<dt>Rules</dt><dd>–</dd>",
      "<dt>Masked columns</dt><dd>–</dd>",
      "<dt>Duration</dt>",
      '<dt>Audit record</dt><dd class="audit-id">4c1d9e07a5b2</dd>',
      "agent 6.4 s · query 12.5 ms · narration 1.9 s · total 8.3 s",
      "3 steps · TBLSTHAR, TBLSTSABIT",
      ">Other facts</h3>",
    ]) {
      expect(en).toContain(text);
    }
    expect(en).not.toMatch(TURKISH);
    const tr = panel("tr");
    for (const text of [
      "Nasıl hesapladım",
      ">Kopyala</button>",
      "<dt>Mod</dt><dd>full_rules</dd>",
      "<dt>Süre</dt>",
      "ajan 6,4 sn · sorgu 12,5 ms · anlatı 1,9 sn · toplam 8,3 sn",
      "3 adım · TBLSTHAR, TBLSTSABIT",
      ">Diğer olgular</h3>",
    ]) {
      expect(tr).toContain(text);
    }
  });

  it("adım satırının aracı çevrilir; modelin cümlesi ve satır dökümü olduğu gibi kalır", () => {
    const dump = {
      status: "answered",
      sql: "SELECT a FROM T",
      steps: [
        { tool: "", ok: true, summary: "a | 1\nb | 2" },
        { tool: "get_schema", ok: true, summary: "Read the columns of TBLSTHAR." },
      ],
    };
    expect(panel("tr", dump)).toContain('<span class="step-tool">yanıt</span>');
    expect(panel("tr", dump)).toContain(">2 satır döndü</span>");
    const en = panel("en", dump);
    expect(en).toContain('<span class="step-tool">answer</span>');
    expect(en).toContain(">2 rows returned</span>");
    expect(en).toContain(">Read the columns of TBLSTHAR.</span>");
    expect(en).not.toContain("a | 1");

    // Teklik İngilizcede ayrı okunur; Türkçede iki sayım da aynı cümledir.
    const single = { status: "answered", sql: "SELECT a FROM T", steps: [{ tool: "run_sql", ok: true, summary: "a | 1" }] };
    expect(panel("en", single)).toContain(">1 row returned</span>");
    expect(panel("en", single)).toContain(" · 1 step</span>");
    expect(panel("tr", single)).toContain(">1 satır döndü</span>");
    expect(panel("tr", single)).toContain(" · 1 adım</span>");
  });
});

describe("netleştirme ve grafik iki dilde", () => {
  it("başlık ve değiştirme düğmesi çevrili, modelin sorusu olduğu gibi kalır", () => {
    expect(clarify("tr")).toContain(">Netleştirelim</h2>");
    expect(clarify("tr")).toContain(">Soruyu değiştir</button>");
    const en = clarify("en");
    expect(en).toContain(">Please clarify</h2>");
    expect(en).toContain(">Change the question</button>");
    expect(en).toContain(`>${clarification.clarification.question}</p>`);
    expect(en).toContain(`>${clarification.clarification.options[0]}</button>`);
  });

  it("grafiğin etiketi çevrili, boş hali iki dilde de yer açmıyor", () => {
    const spec = { type: "bar", option: { series: [{ type: "bar", data: [1, 2] }] } };
    expect(inLang("tr", <ChartView chart={spec} />)).toContain('role="img" aria-label="Grafik"');
    expect(inLang("en", <ChartView chart={spec} />)).toContain('role="img" aria-label="Chart"');
    for (const lang of ["tr", "en"]) {
      expect(inLang(lang, <ChartView chart={null} />)).toBe("");
      expect(inLang(lang, <ChartView chart={{ type: "bar" }} />)).toBe("");
    }
  });
});

describe("eylem düğmeleri iki dilde koşulur", () => {
  it("panoya ekleme ve indirme notu dilin cümlesini yazıyor", async () => {
    fakeClipboard();
    for (const [lang, idle, pin, note, singleNote, copied] of [
      ["tr", "Panoma ekle", "Panoya eklendi", "5 satır indirildi", "1 satır indirildi", "Kopyalandı"],
      ["en", "Add to my board", "Added to the board", "5 rows downloaded", "1 row downloaded", "Copied"],
    ]) {
      const app = await mount(
        <I18nProvider lang={lang}>
          <AnswerCard payload={PAYLOAD[lang]} onSave={noop} />
        </I18nProvider>,
      );
      expect(app.querySelector("#pin-card").textContent).toBe(idle);
      await click(app.querySelector("#pin-card"));
      expect(app.querySelector("#pin-card").textContent).toBe(pin);

      await click(app.querySelector("#export-csv"));
      expect(app.querySelector(".answer-export-note").textContent).toBe(note);

      await click(app.querySelector("#copy-sql"));
      expect(app.querySelector("#copy-sql").textContent).toBe(copied);
      unmount();

      // Tek satırlık cevabın indirmesi İngilizcede tekli okunur.
      const one = await mount(
        <I18nProvider lang={lang}>
          <AnswerCard payload={{ ...PAYLOAD[lang], rows: [PAYLOAD[lang].rows[0]] }} onSave={noop} />
        </I18nProvider>,
      );
      await click(one.querySelector("#export-xlsx"));
      expect(one.querySelector(".answer-export-note").textContent).toBe(singleNote);
      unmount();
    }
  });
});
