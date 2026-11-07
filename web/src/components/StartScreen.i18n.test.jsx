// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// @vitest-environment jsdom
// T440 (R8-20): panonun kartları, boş pano cümlesi ve hazır soru defterinin iki dili. İki dil aynı
// id kümesini boyar; İngilizce kabuk Türkçe harf taşımaz — kart başlıkları, soruları, sütun adları
// ve sunucunun reddi veridir, çevrilmez, o yüzden İngilizce geçiş İngilizce veriyle yapılır. Türkçe
// çıktı bugünkü cümleleri harfi harfine verir: StartScreen.test.jsx, ReadyQuestionForm.test.jsx ve
// ReadyQuestionsScreen.test.jsx o cümleleri bekliyor.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import en from "../i18n/en.json";
import { I18nProvider } from "../i18n/index.js";
import tr from "../i18n/tr.json";
import * as api from "../lib/api.js";
import { EVERY_ROLE_LABEL, PERSONAL_ROLE_LABEL } from "../lib/startCards.js";
import ReadyQuestionForm from "./ReadyQuestionForm.jsx";
import ReadyQuestionsScreen from "./ReadyQuestionsScreen.jsx";
import StartCard from "./StartCard.jsx";
import StartScreen from "./StartScreen.jsx";

vi.mock("../lib/api.js", async (importOriginal) => ({
  ...(await importOriginal()),
  start: vi.fn(),
  startRefresh: vi.fn(),
  startOpen: vi.fn(),
  readyCreate: vi.fn(async () => ({})),
  readyUpdate: vi.fn(async () => ({})),
  readyRemove: vi.fn(async () => ({})),
  readySuggest: vi.fn(),
  readySuggestStatus: vi.fn(),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const noop = () => {};
const TURKISH = /[çğıöşüÇĞİÖŞÜ]/;
const JOB_POLL_MS = 2000;

// Verinin dili çevrilmez; iki geçiş de kendi verini okur (UsersScreen.i18n.test.jsx'in düzeni).
const DATA = {
  tr: {
    number: "Bu ay net satış",
    chart: "Ay ay satış",
    table: "En çok satan ürünler",
    error: "Kapanmamış cari bakiyesi",
    question: "Bu ay net satışımız ne kadar?",
    label: "Net satış tutarı",
    failure: "Bu giriş bu kolonu göremez.",
  },
  en: {
    number: "Net sales this month",
    chart: "Sales by month",
    table: "Best selling products",
    error: "Open customer balance",
    question: "What is our net sales this month?",
    label: "Net sales amount",
    failure: "This login cannot see this column.",
  },
};

function minutesAgo(minutes) {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

// Pano dört yükü de taşır: sayı, grafik, mini tablo (kişisel) ve yürümeyen sorgunun kartı.
function cards(lang) {
  const d = DATA[lang];
  return [
    {
      id: 11,
      title: d.number,
      question: d.question,
      display: "number",
      personal: false,
      value: 8910.5,
      label: d.label,
      refreshed_at: minutesAgo(5),
    },
    {
      id: 12,
      title: d.chart,
      question: d.question,
      display: "chart",
      personal: false,
      chart: {
        type: "bar",
        option: {
          xAxis: { type: "category", data: ["March", "April"] },
          yAxis: { type: "value" },
          series: [{ type: "bar", data: [7400, 8910] }],
        },
      },
      refreshed_at: minutesAgo(90),
    },
    {
      id: 13,
      title: d.table,
      question: d.question,
      display: "table",
      personal: true,
      columns: ["PRODUCT", "QUANTITY"],
      rows: [["Black tea 500 g", 2480]],
      refreshed_at: null,
    },
    {
      id: 14,
      title: d.error,
      question: d.question,
      display: "number",
      personal: false,
      error: d.failure,
      refreshed_at: null,
    },
  ];
}

const READY = {
  tr: { satis: "Bu ay net satış", draft: "Günlük ziyaret sayısı", common: "Ay ay ciro", personal: "Cari bakiyesi" },
  en: {
    satis: "Net sales this month",
    draft: "Daily visit count",
    common: "Revenue by month",
    personal: "Customer balance",
  },
};

// Sözleşme "ready question": `sql` yalnız sunucuda kalır, ekrana hiçbir yerde düşmez.
function rows(lang) {
  const d = READY[lang];
  const base = {
    dataset: "wwi",
    question: DATA[lang].question,
    display: "number",
    position: 1,
    created_by: "admin",
    approved: true,
    created_at: "2026-10-25T09:00:00+00:00",
  };
  return [
    { ...base, id: 1, business_role: "satis", title: d.satis },
    { ...base, id: 2, business_role: "satis", title: d.draft, display: "table", position: 0, approved: false },
    { ...base, id: 3, business_role: "*", title: d.common, display: "chart", position: 2, approved: false },
    { ...base, id: 4, business_role: null, title: d.personal, created_by: "analyst" },
  ];
}

const PAYLOAD = {
  question: "What is our net sales this month?",
  audit_id: "a1",
  columns: ["PRODUCT", "QUANTITY"],
  rows: [["Black tea 500 g", 2480]],
  row_count: 1,
  chart: null,
};

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

// Kartlar ağdan geldiği için pano işareti karta doğrudan bakarak okunur (StartScreen.test.jsx gibi).
const board = (lang, over = {}) =>
  inLang(lang, <>{cards(lang).map((card) => <StartCard key={card.id} card={{ ...card, ...over }} isAdmin />)}</>);
const readyScreen = (lang) => inLang(lang, <ReadyQuestionsScreen rows={rows(lang)} />);

let container;
let root;

async function mount(lang, element) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => {
    root.render(<I18nProvider lang={lang}>{element}</I18nProvider>);
  });
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

// Sahte zaman kurulan testte `settle`'ın beklemesi gereken bir saat yoktur: zincirli promise'ların
// sırası mikro görevlerle döner (ReadyQuestionsScreen.test.jsx'in düzeni).
async function flush() {
  await act(async () => {
    for (let turn = 0; turn < 10; turn += 1) await Promise.resolve();
  });
}

async function click(node) {
  await act(async () => {
    node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  });
}

afterEach(() => {
  if (root) unmount();
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("panonun kartları iki dilde", () => {
  it("aynı id kümesini boyar: çeviri markup'ı değiştirmez", () => {
    const base = ids(board("tr"));
    expect(base).toContain("chart");
    expect(ids(board("en"))).toEqual(base);
    expect(ids(inLang("en", <StartScreen onChange={noop} onAsk={noop} />))).toEqual(
      ids(inLang("tr", <StartScreen onChange={noop} onAsk={noop} />)),
    );
  });

  it("İngilizce kabuk Türkçe harf ve bugünün cümlesini taşımıyor", () => {
    const html = board("en");
    expect(html).not.toMatch(TURKISH);
    for (const text of [
      ">Refresh</button>",
      ">Remove from board</button>",
      ">Re-approve the SQL</button>",
      "Refreshed 5 min ago",
      "Refreshed 1 hr ago",
      'aria-label="Net sales this month — open as a conversation"',
      "This login cannot see this column.",
    ]) {
      expect(html).toContain(text);
    }
    for (const text of [">Yenile<", ">Panodan çıkar<", ">Yenileniyor…<", "yenilendi", "dk önce", "sa önce"]) {
      expect(html).not.toContain(text);
    }
  });

  it("Türkçe pano bugünkü cümleleri harfi harfine veriyor ve provider'sız haliyle aynı", () => {
    const html = board("tr");
    expect(render(<>{cards("tr").map((card) => <StartCard key={card.id} card={card} isAdmin />)}</>)).toBe(html);
    for (const text of [
      ">Yenile</button>",
      ">Panodan çıkar</button>",
      ">SQL'i yeniden onayla</button>",
      "5 dk önce yenilendi",
      "1 sa önce yenilendi",
      ">Net satış tutarı<",
      ">8.910,5<",
    ]) {
      expect(html).toContain(text);
    }
  });

  it("yükü gelmeyen kartın cümlesi iki dilde okunuyor", () => {
    expect(board("tr", { rows: [], chart: null })).toContain(">Bu soruya uyan kayıt yok.<");
    expect(board("en", { rows: [], chart: null })).toContain(">No records match this question.<");
    expect(board("tr", { chart: null })).toContain(">Kartın grafiği yüklenemedi.<");
    expect(board("en", { chart: null })).toContain(">The card's chart could not be loaded.<");
    expect(board("en", { rows: [], chart: null })).not.toMatch(TURKISH);
  });
});

describe("boş pano iki dilde", () => {
  it("tek cümle ve yöneticinin bağlantısı iki dilde okunuyor", async () => {
    for (const lang of ["tr", "en"]) {
      api.start.mockResolvedValue({ cards: [] });
      const app = await mount(lang, <StartScreen onChange={noop} onAsk={noop} isAdmin />);
      await settle();

      const line = app.querySelector("#start-empty");
      expect(line.textContent).toContain(
        lang === "tr" ? "Panonda henüz kart yok" : "Your board has no cards yet",
      );
      expect(line.querySelector("a").textContent).toBe(lang === "tr" ? "Hazır sorular" : "Ready questions");
      expect(line.querySelector("a").getAttribute("href")).toBe("#/hazir-sorular");
      if (lang === "en") expect(app.textContent).not.toMatch(TURKISH);
      unmount();
    }
  });

  it("Türkçe cümle bugünkü gibi tek paragraf: bağlantı cümlenin içinde kalıyor", async () => {
    api.start.mockResolvedValue({ cards: [] });
    const app = await mount("tr", <StartScreen onChange={noop} onAsk={noop} isAdmin />);
    await settle();

    expect(app.querySelector("#start-empty").textContent).toBe(
      "Panonda henüz kart yok: bir soru sor, cevabını panoya ekle. Onaylanmış hazır sorular " +
        "Hazır sorular ekranında.",
    );
  });
});

describe("hazır soru defteri iki dilde", () => {
  it("aynı id kümesini boyar ve İngilizce kabuk Türkçe harf taşımıyor", () => {
    const base = ids(readyScreen("tr"));
    expect(base).toContain("ready-screen");
    expect(base).toContain("ready-suggest");
    expect(ids(readyScreen("en"))).toEqual(base);

    const html = readyScreen("en");
    expect(html).not.toMatch(TURKISH);
    for (const text of [
      ">Ready questions</h1>",
      ">Ask for suggestions</button>",
      ">Awaiting approval</span>",
      ">Sales</h2>",
      ">Everyone</h2>",
      ">Personal</h2>",
      "Single number · order 1 · admin",
      ">Approve</button>",
      ">Preview</button>",
      ">Open</button>",
      ">Edit</button>",
      ">Delete</button>",
    ]) {
      expect(html).toContain(text);
    }
    for (const text of [">Hazır sorular<", ">Onay bekliyor<", ">Öneri iste<", ">Onayla<", ">Önizle<", "sıra 1"]) {
      expect(html).not.toContain(text);
    }
  });

  it("Türkçe defter bugünkü cümleleri harfi harfine veriyor ve provider'sız haliyle aynı", () => {
    expect(render(<ReadyQuestionsScreen rows={rows("tr")} />)).toBe(readyScreen("tr"));
    const html = readyScreen("tr");
    for (const text of [
      ">Hazır sorular</h1>",
      ">Öneri iste</button>",
      ">Onay bekliyor</span>",
      ">Satış</h2>",
      ">Herkes</h2>",
      ">Kişisel</h2>",
      "Tek sayı · sıra 1 · admin",
      ">Onayla</button>",
      ">Önizle</button>",
      ">Aç</button>",
      ">Düzenle</button>",
      ">Sil</button>",
      'title="Onaysız satır panoda görünmez; yönetici ön izlemesidir."',
    ]) {
      expect(html).toContain(text);
    }
    expect(render(<ReadyQuestionsScreen rows={[]} />)).toContain("Henüz hazır soru yok");
    expect(inLang("en", <ReadyQuestionsScreen rows={[]} />)).toContain("No ready questions yet");
    expect(inLang("en", <ReadyQuestionsScreen rows={[]} loading />)).toContain("Reading ready questions…");
  });

  it("silme onayı ve onayın cevabı iki dilde okunuyor", async () => {
    for (const lang of ["tr", "en"]) {
      const app = await mount(lang, <ReadyQuestionsScreen rows={rows(lang)} onRefresh={noop} />);
      await click(app.querySelector('[data-ready-delete="1"]'));
      expect(app.textContent).toContain(lang === "tr" ? "Silinsin mi?" : "Delete it?");
      expect(app.textContent).toContain(lang === "tr" ? "Evet" : "Yes");

      api.readyUpdate.mockResolvedValueOnce({ ready_question: {} });
      await click(app.querySelector('[data-ready-approve="2"]'));
      await settle();
      expect(app.querySelector("#ready-note").textContent).toBe(
        lang === "tr"
          ? "“Günlük ziyaret sayısı” onaylandı; kart artık panoda."
          : "“Daily visit count” is approved; the card is on the board now.",
      );
      unmount();
    }
  });

  it("öneri işinin aşaması iki dilde okunuyor", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    api.readySuggest.mockResolvedValue({ job_id: "j1", phase: "asking", asked: 0, stored: 0, message: null });
    api.readySuggestStatus.mockResolvedValue({ job_id: "j1", phase: "done", asked: 12, stored: 9, message: null });

    for (const lang of ["tr", "en"]) {
      const app = await mount(lang, <ReadyQuestionsScreen rows={rows(lang)} onRefresh={noop} />);
      await click(app.querySelector("#ready-suggest"));
      await flush();

      expect(app.querySelector("#ready-job").textContent).toBe(
        lang === "tr"
          ? "Öneri koşuyor: 0 soru soruldu, 0 aday eklendi."
          : "Suggestion run: 0 questions asked, 0 candidates added.",
      );

      await act(async () => {
        vi.advanceTimersByTime(JOB_POLL_MS);
      });
      await flush();
      expect(app.querySelector("#ready-job").textContent).toBe(
        lang === "tr"
          ? "Öneri bitti: 12 soru soruldu, 9 aday onay bekliyor."
          : "Suggestion run finished: 12 questions asked, 9 candidates awaiting approval.",
      );
      unmount();
    }
  });
});

describe("hazır soru formu iki dilde", () => {
  it("rol ve görünüm seçenekleri ile etiketler iki dilde katalogdan okunuyor", async () => {
    const OPTIONS = {
      tr: {
        role: ["Herkes", "Satış", "Satın alma", "Muhasebe", "Yönetim", "Genel"],
        display: ["Tek sayı", "Grafik", "Tablo"],
        suggested: "Sonucun biçiminden önerilen: Tablo.",
      },
      en: {
        role: ["Everyone", "Sales", "Purchasing", "Accounting", "Management", "General"],
        display: ["Single number", "Chart", "Table"],
        suggested: "Suggested by the shape of the result: Table.",
      },
    };

    for (const lang of ["tr", "en"]) {
      const app = await mount(lang, <ReadyQuestionForm payload={PAYLOAD} onCancel={noop} />);
      const options = (id) => Array.from(app.querySelectorAll(`#${id} option`), (node) => node.textContent);

      expect(options("ready-role")).toEqual(OPTIONS[lang].role);
      expect(options("ready-display")).toEqual(OPTIONS[lang].display);
      expect(app.textContent).toContain(OPTIONS[lang].suggested);
      expect(app.querySelector("#ready-save").textContent).toBe(lang === "tr" ? "Kaydet" : "Save");
      unmount();
    }
  });

  it("kaydın cümlesi kartı kimin panosuna eklediğini iki dilde söylüyor", async () => {
    for (const lang of ["tr", "en"]) {
      const app = await mount(lang, <ReadyQuestionForm payload={PAYLOAD} onCancel={noop} />);
      await click(app.querySelector("#ready-save"));
      await settle();

      expect(app.querySelector("#ready-saved").textContent).toBe(
        lang === "tr" ? "Hazır soru eklendi: Herkes için panoda." : "Ready question added: on the board for Everyone.",
      );
      expect(app.querySelector("#ready-cancel").textContent).toBe(lang === "tr" ? "Kapat" : "Close");
      if (lang === "en") expect(app.textContent).not.toMatch(TURKISH);
      unmount();
    }
  });
});

describe("rol adları iki yerde yazılmıyor", () => {
  it("startCards'ın iki sabiti Türkçe katalog değerlerinin kendisidir", () => {
    expect(EVERY_ROLE_LABEL).toBe(tr["start.role.every"]);
    expect(PERSONAL_ROLE_LABEL).toBe(tr["start.role.personal"]);
    expect(en["start.role.every"]).toBe("Everyone");
    expect(en["start.card.refreshed"]).toContain("{time}");
    expect(tr["start.card.refreshed"]).toBe("{time} yenilendi");
    expect(en["ready.order"]).toBe("order {count}");
  });
});
