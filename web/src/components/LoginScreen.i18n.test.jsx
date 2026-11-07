// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// @vitest-environment jsdom
// R8-17: kartın ve kapının her cümlesi katalogdan. İki dil aynı id kümesini boyamalı, İngilizce
// çıktıda Türkçe harf kalmamalı, Türkçe çıktı bugünkü cümleleri harfi harfine vermeli — kartı
// ölçen öteki testler o cümleleri bekliyor. Sunucunun reddi (`detail`) çevrilmez, geldiği dilde
// yazılır; testin İngilizce cümlesi de bu yüzden olduğu gibi görünmeli.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import Root from "../Root.jsx";
import { I18nProvider } from "../i18n/index.js";
import LoginScreen from "./LoginScreen.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const TR = {
  title: "Bilgin",
  lead: "Sormaya devam etmek için oturum açın.",
  tagline: "Veritabanınıza Türkçe soru sorun; SQL'i Bilgin yazar.",
  username: "Kullanıcı adı",
  password: "Parola",
  submit: "Giriş",
  submitting: "Giriş yapılıyor…",
  failed: "Giriş yapılamadı.",
};

const EN = {
  title: "Bilgin",
  lead: "Sign in to keep asking.",
  tagline: "Ask your database in plain language; Bilgin writes the SQL.",
  username: "Username",
  password: "Password",
  submit: "Sign in",
  submitting: "Signing in…",
  failed: "Sign-in failed.",
};

// Boş kartta boyananlar: `submitting` yalnız bekleyen girişte, `failed` yalnız başlıksız hatada
// okunur — ikisi de aşağıdaki etkileşim testlerinde sınavını veriyor.
const SHOWN = ["title", "lead", "tagline", "username", "password", "submit"];

// Ürünün adı iki dilde aynı; öteki cümleler İngilizce kartın içine sızmamalı.
const TRANSLATED = ["lead", "tagline", "username", "password", "submit", "submitting", "failed"];

const TURKISH = /[çğıöşüÇĞİÖŞÜ]/;
const DECLINED_EN = "Wrong username or password.";

// Cümlelerdeki kesme işareti ve tırnak SSR çıktısında düz karakter değildir; okunur metin öyle aranır.
function render(element) {
  return renderToStaticMarkup(element)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&");
}

const noop = () => {};
const inLang = (lang, element) => render(<I18nProvider lang={lang}>{element}</I18nProvider>);
const card = (lang) => inLang(lang, <LoginScreen onLogin={noop} />);
const gate = (lang, initial) => inLang(lang, <Root initial={initial} />);
const ids = (html) => [...html.matchAll(/id="([^"]+)"/g)].map((match) => match[1]).sort();

let container;
let root;

async function mount(node) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => {
    root.render(node);
  });
  return container;
}

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function click(node) {
  await act(async () => {
    node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  });
}

// React kontrollü girdiye yazmak değeri yerleştirmeyi değil, yerel değiştiriciyi çağırmayı ister.
async function fill(node, value) {
  const setter = Object.getOwnPropertyDescriptor(node.constructor.prototype, "value").set;
  await act(async () => {
    setter.call(node, value);
    node.dispatchEvent(new Event("input", { bubbles: true }));
    node.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

// Zorunlu iki alan dolu gönderilsin: denetimi boş alan keserse reddin cümlesi hiç yazılmaz.
async function submit(app) {
  await fill(app.querySelector("#login-username"), "eren");
  await fill(app.querySelector("#login-password"), "gizli-parola");
  await click(app.querySelector("#login-submit"));
  await settle();
}

afterEach(() => {
  if (root) {
    act(() => root.unmount());
    root = undefined;
  }
  container?.remove();
  container = undefined;
});

describe("giriş kartı iki dilde", () => {
  it("aynı id kümesini boyar: çeviri markup'ı değiştirmez", () => {
    const tr = ids(card("tr"));
    expect(tr.length).toBeGreaterThan(0);
    expect(ids(card("en"))).toEqual(tr);
  });

  it("İngilizce kartta Türkçe harf ve bugünün cümlesi kalmıyor", () => {
    const html = card("en");
    expect(html).not.toMatch(TURKISH);
    for (const key of SHOWN) expect(html).toContain(EN[key]);
    for (const key of TRANSLATED) expect(html).not.toContain(TR[key]);
  });

  it("Türkçe kart bugünkü metni harfi harfine veriyor", () => {
    const html = card("tr");
    for (const key of SHOWN) expect(html).toContain(TR[key]);
    // Provider'sız ağaç (kartı ölçen öteki testlerin kurduğu) tr katalogla aynı baytı üretir.
    expect(render(<LoginScreen onLogin={noop} />)).toBe(html);
  });
});

describe("giriş kartının iki dilli hâlleri", () => {
  for (const [lang, text] of [["tr", TR], ["en", EN]]) {
    it(`${lang}: reddin cümlesi verildiği dilde yazılıyor`, async () => {
      const app = await mount(
        <I18nProvider lang={lang}>
          <LoginScreen onLogin={() => Promise.reject(new Error(DECLINED_EN))} />
        </I18nProvider>,
      );
      await submit(app);
      expect(app.querySelector("#login-error").textContent).toBe(DECLINED_EN);
    });

    it(`${lang}: başlıksız hata katalogun cümlesine düşüyor`, async () => {
      const app = await mount(
        <I18nProvider lang={lang}>
          <LoginScreen onLogin={() => Promise.reject(new Error(""))} />
        </I18nProvider>,
      );
      await submit(app);
      expect(app.querySelector("#login-error").textContent).toBe(text.failed);
    });

    it(`${lang}: bekleyen girişte düğme yazılıyor ve basılamıyor`, async () => {
      const app = await mount(
        <I18nProvider lang={lang}>
          <LoginScreen onLogin={() => new Promise(() => {})} />
        </I18nProvider>,
      );
      await fill(app.querySelector("#login-username"), "eren");
      await fill(app.querySelector("#login-password"), "gizli-parola");
      await click(app.querySelector("#login-submit"));

      const submitButton = app.querySelector("#login-submit");
      expect(submitButton.textContent).toBe(text.submitting);
      expect(submitButton.disabled).toBe(true);
    });
  }
});

describe("oturum kapısı iki dilde", () => {
  it("açılış logosu ve giriş kartı İngilizce çıktıda Türkçe harf taşımıyor", () => {
    const checking = gate("en", { screen: "checking" });
    expect(checking).not.toMatch(TURKISH);
    expect(checking).toContain(`>${EN.title}</span>`);
    expect(gate("en", { screen: "login", user: null, requested: "#/" })).not.toMatch(TURKISH);
  });

  it("Türkçe kapı bugünkü logosunu ve kartını koruyor", () => {
    expect(gate("tr", { screen: "checking" })).toContain(`>${TR.title}</span>`);
    expect(gate("tr", { screen: "login", user: null, requested: "#/" })).toContain(TR.lead);
  });
});
