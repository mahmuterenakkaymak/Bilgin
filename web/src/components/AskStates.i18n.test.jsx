// @vitest-environment jsdom
// R8-18: soru akışının kendi cümleleri iki dilde — kutu, adımlar, hata kartı ve uyarı bandı. İki dil
// aynı id kümesini boyamalı, İngilizce çıktıda Türkçe harf kalmamalı, Türkçe çıktı bugünkü cümleleri
// harfi harfine vermeli — AskStates.test.jsx, AskBoxCleared.test.jsx ve StartScreen.test.jsx o
// cümleleri bekliyor. Sunucunun cümlesi (error.message, answer_text, uyarıların mesajı) ve verinin
// örnek sorusu çevrilmez, geldiği dilde yazılır; testin İngilizce cümlesi de bu yüzden öyle duruyor.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n/index.js";
import { STEP_KEYS, STEP_MS } from "../lib/steps.js";
import AskBox from "./AskBox.jsx";
import ErrorCard from "./ErrorCard.jsx";
import LoadingSteps from "./LoadingSteps.jsx";
import Warnings from "./Warnings.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const noop = () => {};
const TURKISH = /[çğıöşüÇĞİÖŞÜ]/;

const TR = {
  placeholder: "Sorunuzu yazın",
  label: 'aria-label="Soru"',
  submit: ">Sor</button>",
  answering: "Cevaplanıyor…",
  hint: "Enter ile gönder, Shift+Enter alt satır.",
  steps: ["Soru okunuyor", "Şema aranıyor", "SQL çalıştırılıyor", "Cevap yazılıyor"],
  rebuild: ">İndeksi yeniden kur</button>",
  rebuildFailed: "İndeks yeniden kurulamadı.",
  warning: "Satır sayısı join yüzünden şişmiş olabilir.",
};

const EN = {
  placeholder: "Write your question",
  label: 'aria-label="Question"',
  submit: ">Ask</button>",
  answering: "Answering…",
  hint: "Press Enter to send, Shift+Enter for a new line.",
  steps: ["Reading the question", "Searching the schema", "Running the SQL", "Writing the answer"],
  rebuild: ">Rebuild the index</button>",
  rebuildFailed: "The index could not be rebuilt.",
  warning: "The row count may be inflated by a join.",
};

// Kartın dört hali: payload'ın hatası hangi adla gelirse o başlığa iner, tanınmayan gene düşer.
const CARDS = [
  { kind: "llm_error", tr: "Model yanıt vermiyor", en: "The model is not responding" },
  { kind: "index", tr: "İndeks eski", en: "Index out of date" },
  { kind: "network", tr: "Sunucuya ulaşılamadı", en: "The server could not be reached" },
  { kind: "exec:sql", tr: "Cevap üretilemedi", en: "No answer" },
];

// Sunucunun cümlesi: çevrilmez, verildiği dilde okunur.
const SENTENCE = {
  tr: "Model endpoint'ine ulaşılamadı: http://127.0.0.1:8080/v1.",
  en: "The model endpoint could not be reached: http://127.0.0.1:8080/v1.",
};

const WARNINGS = { tr: [{ code: "fanout", message: TR.warning }], en: [{ code: "fanout", message: EN.warning }] };

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
const box = (lang, props) => inLang(lang, <AskBox value="" onChange={noop} onAsk={noop} {...props} />);
const card = (lang, kind) => inLang(lang, <ErrorCard kind={kind} message={SENTENCE[lang]} onRebuild={noop} />);
const band = (lang) => inLang(lang, <Warnings warnings={WARNINGS[lang]} />);

let container;
let root;

async function mount(node) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(node));
  return container;
}

// Adım yazısı geçen süreden ilerlediği için saat sahte: her devir kartı bir adım ileri taşır.
async function steps(lang) {
  vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
  const app = await mount(<I18nProvider lang={lang}><LoadingSteps /></I18nProvider>);
  const shown = [];
  for (let index = 0; index < STEP_KEYS.length; index += 1) {
    const line = app.querySelector(".loading-step");
    shown.push([line.firstChild.textContent.trim(), line.querySelector(".loading-count").textContent.trim()]);
    await act(async () => vi.advanceTimersByTime(STEP_MS));
  }
  act(() => root.unmount());
  root = undefined;
  container.remove();
  container = undefined;
  return shown;
}

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

afterEach(() => {
  if (root) act(() => root.unmount());
  container?.remove();
  container = undefined;
  root = undefined;
  vi.useRealTimers();
});

describe("soru kutusu iki dilde", () => {
  it("aynı id kümesini boyar: çeviri markup'ı değiştirmez", () => {
    const tr = ids(box("tr"));
    expect(tr).toContain("question");
    expect(ids(box("en"))).toEqual(tr);
  });

  it("İngilizce kutuda Türkçe harf ve bugünün cümlesi kalmıyor", () => {
    const html = box("en");
    expect(html).not.toMatch(TURKISH);
    for (const text of [EN.placeholder, EN.label, EN.submit, EN.hint]) expect(html).toContain(text);
    for (const text of [TR.placeholder, TR.submit, TR.hint]) expect(html).not.toContain(text);
  });

  it("Türkçe kutu bugünkü metni harfi harfine veriyor", () => {
    const html = box("tr");
    for (const text of [TR.placeholder, TR.label, TR.submit, TR.hint]) expect(html).toContain(text);
    // Provider'sız kutu (öteki testlerin kurduğu) tr katalogla aynı baytı üretir.
    expect(render(<AskBox value="" onChange={noop} onAsk={noop} />)).toBe(html);
  });

  it("koşan sorunun düğme yazısı iki dilde de kilitli", () => {
    for (const [lang, text] of [["tr", TR.answering], ["en", EN.answering]]) {
      const html = box(lang, { loading: true, value: "Kimler?" });
      expect(html).toContain(text);
      expect(/<button[^>]*id="ask-button"[^>]*>/.exec(html)[0]).toContain("disabled");
    }
  });

  it("örnek çipin sorusu verinin cümlesidir: İngilizce kutuda da çevrilmez", () => {
    const examples = [{ question: "En çok satan beş ürün hangisi?", kind: "golden" }];
    expect(box("en", { examples })).toContain(">En çok satan beş ürün hangisi?</button>");
  });
});

describe("bekleme kartı iki dilde", () => {
  it("dört adım iki dilde de sırayla ilerliyor ve sayımı aynı", async () => {
    const tr = await steps("tr");
    const en = await steps("en");
    expect(tr.map(([text]) => text)).toEqual(TR.steps);
    expect(en.map(([text]) => text)).toEqual(EN.steps);
    expect(en.map(([, count]) => count)).toEqual(["1 / 4", "2 / 4", "3 / 4", "4 / 4"]);
  });

  it("İngilizce adım yazılarında Türkçe harf kalmıyor", async () => {
    for (const [text] of await steps("en")) expect(text).not.toMatch(TURKISH);
  });
});

describe("hata kartı iki dilde", () => {
  it("her tür aynı id kümesini boyuyor", () => {
    for (const entry of CARDS) {
      const tr = ids(card("tr", entry.kind));
      expect(tr).toContain("error-card");
      expect(ids(card("en", entry.kind))).toEqual(tr);
    }
  });

  it("İngilizce kart Türkçe harf taşımıyor ve sunucunun cümlesini olduğu gibi yazıyor", () => {
    for (const entry of CARDS) {
      const html = card("en", entry.kind);
      expect(html).not.toMatch(TURKISH);
      expect(html).toContain(entry.en);
      expect(html).toContain(SENTENCE.en);
      expect(html).not.toContain(entry.tr);
    }
  });

  it("Türkçe kart bugünkü başlıklarını veriyor ve provider'sız haliyle aynı", () => {
    for (const entry of CARDS) {
      const html = card("tr", entry.kind);
      expect(html).toContain(entry.tr);
      expect(html).toContain(SENTENCE.tr);
      expect(render(<ErrorCard kind={entry.kind} message={SENTENCE.tr} onRebuild={noop} />)).toBe(html);
    }
  });

  it("yeniden kurma düğmesi yalnız indeks kartında ve iki dilde de çevrili", () => {
    expect(card("tr", "index")).toContain(TR.rebuild);
    expect(card("en", "index")).toContain(EN.rebuild);
    for (const kind of ["llm_error", "network", "exec:sql"]) {
      expect(card("en", kind)).not.toContain('id="error-rebuild"');
      expect(card("tr", kind)).not.toContain('id="error-rebuild"');
    }
  });

  it("kuramama cümlesi iki dilde de kataloğun", async () => {
    for (const [lang, text] of [["tr", TR.rebuildFailed], ["en", EN.rebuildFailed]]) {
      const app = await mount(
        <I18nProvider lang={lang}>
          <ErrorCard kind="index" onRebuild={() => Promise.reject(new Error(""))} />
        </I18nProvider>,
      );
      await act(async () => app.querySelector("#error-rebuild").click());
      await settle();
      expect(app.textContent).toContain(text);
      act(() => root.unmount());
      root = undefined;
      app.remove();
      container = undefined;
    }
  });
});

describe("uyarı bandı iki dilde", () => {
  it("aynı bandı boyuyor ve mesajı verildiği dilde bırakıyor", () => {
    const tr = band("tr");
    expect(ids(band("en"))).toEqual(ids(tr));
    expect(tr).toContain(TR.warning);
    const en = band("en");
    expect(en).toContain(EN.warning);
    expect(en).not.toMatch(TURKISH);
  });

  it("uyarı yoksa iki dilde de bant hiç kurulmuyor", () => {
    for (const lang of ["tr", "en"]) expect(inLang(lang, <Warnings warnings={[]} />)).toBe("");
  });
});
