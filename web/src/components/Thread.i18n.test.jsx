// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// @vitest-environment jsdom
// R8-19: kenar çubuğu ve konuşma akışı iki dilde — bölüm başlıkları, boş cümleler, silme onayı,
// tur sayısı, kısa zaman ve katlanmış turun yeniden koşum notu. İki dil aynı id kümesini boyamalı;
// İngilizce çıktının kabarı Türkçe harf taşımamalı; Türkçe çıktı bugünkü cümleleri harfi harfine
// vermeli — Sidebar.test.jsx, ConversationList.test.jsx ve Thread.test.jsx o cümleleri bekliyor.
// Verinin kendisi (sorular, cevap cümlesi, hücreler) çevrilmez; sayı arayüzün diliyle okunur.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n/index.js";
import * as api from "../lib/api.js";
import { initialState, threadReducer } from "../lib/thread.js";
import ConversationList from "./ConversationList.jsx";
import Sidebar from "./Sidebar.jsx";
import Thread from "./Thread.jsx";

// Silme istekleri ağa çıkmaz: onay cümlesi ve başarısızlığın notu okunur.
vi.mock("../lib/api.js", async (importOriginal) => ({
  ...(await importOriginal()),
  conversationDelete: vi.fn(),
  savedRemove: vi.fn(),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const noop = () => {};
const TURKISH = /[çğıöşüÇĞİÖŞÜ]/;

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
// Saatler yerelden kuruluyor: "dün" takvimsel bir fark, makinenin saat diliminden bağımsız olmalı.
const NOON = new Date(2026, 9, 25, 12, 0, 0).getTime();
const ago = (ms) => new Date(NOON - ms).toISOString();

// İngilizce kenar çubuğu: satırların kendisi veridir, o yüzden İngilizce kuruluyor ki kabarı ölçülebilsin.
const SAVED = [
  { id: 7, question: "What was our net sales in September 2026?", created_at: ago(2 * MINUTE) },
  { id: 6, question: "Top five products", created_at: ago(30 * HOUR) },
];

const HISTORY = [
  { audit_id: "h1", question: "Net revenue last month", status: "answered", ts: ago(4 * MINUTE) },
  { audit_id: "h2", question: "Which product sold the most?", status: "needs_clarification", ts: ago(3 * HOUR), conversation_id: "c1", turn: 1 },
  { audit_id: "h3", question: "Stock by depot", status: "failed", ts: ago(5 * DAY) },
];

const CONVERSATIONS = [
  { id: "c1", title: "September sales", last_question: "What is Ankara's share?", updated_at: ago(2 * MINUTE), turns: 3 },
  { id: "c2", title: "", updated_at: ago(2 * DAY), turns: 1 },
];

// Depodan açılmış üç turluk konuşma (Contracts "StoredTurn"): yük yoktur, kartın kabarı kataloğundur.
const TURN = {
  n: 1,
  question: "How much did we sell in September 2026?",
  choice: null,
  status: "answered",
  sql: "SELECT SUM(QTY) FROM SALES",
  answer_text: "September 2026 sales were 8910 units.",
  audit_id: "aa1",
  created_at: "2026-10-20T09:00:00+00:00",
  summary: {
    columns: ["PRODUCT_NAME", "TOTAL_SALES"],
    row_count: 2,
    rows: [["Black Tea 500 g", 2480], ["Wheat Flour 500 g", 2140]],
    facts: [],
    chart_kind: "bar",
    context: null,
    clarification: null,
  },
};

const stored = (n, question) => ({ ...TURN, n, question, audit_id: `aa${n}` });

function thread(...actions) {
  return actions.reduce((state, action) => threadReducer(state, action), initialState);
}

// İlk tur açılmış: Kapat düğmesi ancak açılmış eski turda kurulur, son tur hiç katlanmaz.
const THREE = thread(
  {
    type: "load",
    conversation: { id: "c1" },
    turns: [
      stored(1, "How much did we sell in September 2026?"),
      stored(2, "And in August?"),
      stored(3, "How many orders did this customer place?"),
    ],
  },
  { type: "expand", n: 1 },
);

// Cümlesi olmayan başarısız tur: indirgeyici metin uydurmaz, kartın kataloğu okunur (R8-19).
const FAILED = thread({
  type: "load",
  conversation: { id: "c1" },
  turns: [{ ...TURN, status: "failed", answer_text: "", summary: { ...TURN.summary, rows: [], row_count: 0 } }],
});

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

// Zaman her iki listenin kendi Date.now()'undan okunduğu için her boyama saat kurulu koşar.
function atNoon(run) {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOON);
  try {
    return run();
  } finally {
    vi.useRealTimers();
  }
}

const lists = (props = {}) => ({ saved: SAVED, history: HISTORY, conversations: CONVERSATIONS, ...props });
const sidebar = (lang, props = {}) => atNoon(() => inLang(lang, <Sidebar onAsk={noop} onRemoved={noop} {...lists(props)} />));
const flow = (lang, state = THREE) =>
  inLang(lang, <Thread turns={state.turns} onExpand={noop} onReplay={noop} onChoose={noop} onChange={noop} onSave={noop} />);
const screen = (lang) =>
  atNoon(() =>
    inLang(
      lang,
      <>
        <Sidebar onAsk={noop} onRemoved={noop} {...lists()} />
        <Thread turns={THREE.turns} onReplay={noop} />
      </>,
    ),
  );

const times = (html) => [...html.matchAll(/class="side-time">([^<]*)</g)].map((match) => match[1]);

let container;
let root;

async function mount(node) {
  container = document.createElement("div");
  document.body.append(container);
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

async function click(node) {
  await act(async () => node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })));
}

beforeEach(() => {
  window.location.hash = "#/";
  vi.spyOn(window, "confirm");
});

afterEach(() => {
  if (root) unmount();
  container?.remove();
  container = undefined;
  root = undefined;
  window.location.hash = "#/";
  vi.restoreAllMocks();
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("kenar çubuğu ve akış iki dilde", () => {
  it("aynı id kümesini boyar: çeviri markup'ı değiştirmez", () => {
    const tr = ids(screen("tr"));
    for (const id of ["saved-list", "conversation-list", "history-list", "thread"]) expect(tr).toContain(id);
    expect(ids(screen("en"))).toEqual(tr);
  });

  it("İngilizce kabarı Türkçe harf ve bugünün cümlesi taşımıyor", () => {
    const html = sidebar("en") + flow("en");
    expect(html).not.toMatch(TURKISH);
    for (const text of [
      ">Saved questions</h2>",
      ">Conversations</h2>",
      ">History</h2>",
      ">Run it again</button>",
      "Run it again for the full table and chart.",
      ">Close</button>",
      ">3 turns</span>",
      ">1 turn</span>",
      '<span class="side-time">4 min ago</span>',
      '<span class="side-time">yesterday</span>',
    ]) {
      expect(html).toContain(text);
    }
    for (const text of [
      ">Kayıtlı sorular<",
      ">Konuşmalar<",
      ">Geçmiş<",
      ">Yeniden çalıştır<",
      ">Kapat<",
      ">3 tur<",
      "Tam tablo ve grafik için yeniden çalıştırın.",
    ]) {
      expect(html).not.toContain(text);
    }
  });

  it("Türkçe bugünkü cümleleri harfi harfine veriyor ve provider'sız haliyle aynı", () => {
    const html = sidebar("tr") + flow("tr");
    for (const text of [
      ">Kayıtlı sorular</h2>",
      ">Konuşmalar</h2>",
      ">Geçmiş</h2>",
      ">Yeniden çalıştır</button>",
      "Tam tablo ve grafik için yeniden çalıştırın.",
      ">Kapat</button>",
      ">3 tur</span>",
      ">1 tur</span>",
      '<span class="side-time">2 dk önce</span>',
      '<span class="side-time">dün</span>',
      'aria-label="Kaydı sil"',
      'aria-label="Konuşmayı sil"',
    ]) {
      expect(html).toContain(text);
    }
    const bare = atNoon(() => render(<Sidebar onAsk={noop} onRemoved={noop} {...lists()} />));
    expect(bare).toBe(sidebar("tr"));
  });

  it("boş üç liste iki dilde de kendi cümlesini yazıyor", () => {
    const empty = { saved: [], history: [], conversations: [] };
    const en = sidebar("en", empty);
    for (const text of ["No saved questions yet.", "No conversations yet.", "History is empty."]) expect(en).toContain(text);
    const tr = sidebar("tr", empty);
    for (const text of ["Henüz kayıtlı soru yok.", "Henüz konuşma yok.", "Geçmiş boş."]) expect(tr).toContain(text);
  });

  it("başlıksız konuşma iki dilde de adını katalogdan alıyor", () => {
    const label = (lang) => {
      const html = sidebar(lang, { conversations: [{ id: "c9", title: "", updated_at: "", turns: 1 }] });
      const rows = html.split('id="conversation-list"')[1];
      return /class="side-label">([^<]*)</.exec(rows)[1];
    };
    expect(label("tr")).toBe("Cevapsız konuşma");
    expect(label("en")).toBe("Conversation with no answer");
  });
});

describe("kısa zaman iki dilde", () => {
  const AGES = [
    [1000, "şimdi", "just now"],
    [2 * MINUTE, "2 dk önce", "2 min ago"],
    [3 * HOUR, "3 sa önce", "3 hr ago"],
    [30 * HOUR, "dün", "yesterday"],
    [5 * DAY, "5 gün önce", "5 days ago"],
    [7 * DAY, "1 hafta önce", "1 week ago"],
    [14 * DAY, "2 hafta önce", "2 weeks ago"],
    [35 * DAY, "1 ay önce", "1 month ago"],
    [70 * DAY, "2 ay önce", "2 months ago"],
    [400 * DAY, "1 yıl önce", "1 year ago"],
    [800 * DAY, "2 yıl önce", "2 years ago"],
  ];

  const aged = AGES.map(([ms], index) => ({ id: index, question: `Question ${index}`, created_at: ago(ms) }));

  it("her kupa iki dilde de kataloğun cümlesi; İngilizce tekli ayrı okunur", () => {
    const only = { history: [], conversations: [] };
    expect(times(sidebar("en", { ...only, saved: aged }))).toEqual(AGES.map(([, , en]) => en));
    expect(times(sidebar("tr", { ...only, saved: aged }))).toEqual(AGES.map(([, tr]) => tr));
  });

  it("bozuk ya da boş zaman iki dilde de satırı zamansız bırakıyor", () => {
    const saved = [
      { id: 1, question: "No time", created_at: "" },
      { id: 2, question: "Broken time", created_at: "2026-13-45" },
    ];
    for (const lang of ["tr", "en"]) {
      const html = sidebar(lang, { saved, history: [], conversations: [] });
      expect(html).not.toContain('class="side-time"');
      expect(html).not.toContain("undefined");
      expect(html).not.toContain("Invalid");
    }
  });
});

describe("başarısız turun cümlesi iki dilde", () => {
  it("sunucunun cümlesi yoksa kart kataloğunu okuyor", () => {
    expect(flow("tr", FAILED)).toContain('<p class="turn-sentence">Cevap üretilemedi.</p>');
    const en = flow("en", FAILED);
    expect(en).toContain('<p class="turn-sentence">The answer could not be produced.</p>');
    expect(en).not.toMatch(TURKISH);
  });

  it("Türkçe cevap cümlesi İngilizce arayüzde çevrilmez", () => {
    const turkish = thread({
      type: "load",
      conversation: { id: "c1" },
      turns: [{ ...TURN, answer_text: "Eylül 2026 satışı 8.910 adet.", question: "Eylül satışı ne kadar?" }],
    });
    const html = flow("en", turkish);
    expect(html).toContain("Eylül 2026 satışı 8.910 adet.");
    expect(html).toContain("Eylül satışı ne kadar?");
  });
});

describe("silme cümleleri iki dilde koşulur", () => {
  it("konuşmayı silme onayının cümlesi arayüzün dili", async () => {
    for (const [lang, question] of [["tr", "Konuşma silinsin mi?"], ["en", "Delete this conversation?"]]) {
      window.confirm.mockReturnValue(false);
      const app = await mount(
        <I18nProvider lang={lang}>
          <ConversationList conversations={[{ id: "c1", title: "September sales", updated_at: "", turns: 1 }]} />
        </I18nProvider>,
      );
      await click(app.querySelector("[data-conversation-delete]"));
      expect(window.confirm).toHaveBeenCalledWith(question);
      expect(api.conversationDelete).not.toHaveBeenCalled();
      unmount();
    }
  });

  it("silme başarısız olursa notun cümlesi kataloğun, sunucununki değil", async () => {
    api.savedRemove.mockRejectedValue(new Error(""));
    for (const [lang, note] of [["tr", "Kayıt silinemedi."], ["en", "The saved question could not be deleted."]]) {
      const app = await mount(
        <I18nProvider lang={lang}>
          <Sidebar onAsk={noop} onRemoved={noop} saved={[{ id: 3, question: "Top five products" }]} />
        </I18nProvider>,
      );
      await click(app.querySelector(".side-remove"));
      await act(async () => Promise.resolve());
      expect(app.querySelector(".side-note")?.textContent).toBe(note);
      unmount();
    }
  });
});
