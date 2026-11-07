// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// R8-15: katalog eşitliği, çevirinin düşüş zinciri ve dil sırası. Ekranlar anahtarlarını kendi
// görevinde ekleyeceği için eşitlik testleri kayıttaki değil dosyadaki kataloglara bakar.
import { createElement, Fragment } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import en from "./en.json";
import { I18nProvider, SUPPORTED, loadCatalog, pickLang, registerCatalog, useT } from "./index.js";
import tr from "./tr.json";

const keyNames = (catalog) => Object.keys(catalog).sort();
const paramNames = (catalog) =>
  Object.fromEntries(
    Object.entries(catalog).map(([key, text]) => [
      key,
      [...String(text).matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort(),
    ]),
  );

describe("kataloglar", () => {
  it("iki dilde aynı anahtarlar ve aynı parametre adları vardır", () => {
    expect(keyNames(en)).toEqual(keyNames(tr));
    expect(paramNames(en)).toEqual(paramNames(tr));
  });

  it("desteklenen diller tr ve en", () => {
    expect(SUPPORTED).toEqual(["tr", "en"]);
  });
});

// Kayıt bu dosyada örnek katalogla sınanır; diğer test dosyaları test-setup'ın gerçek kataloğunu görür.
registerCatalog("tr", { "selam": "Merhaba {ad}", "sadece.tr": "Yalnız Türkçe" });
registerCatalog("en", { "selam": "Hello {name}" });

function Label() {
  const { t, lang } = useT();
  return createElement(Fragment, null, `${lang}|${t("selam", { ad: "Dünya", name: "World" })}`);
}

const text = (element) =>
  renderToStaticMarkup(element)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&");

describe("useT", () => {
  it("provider olmayan ağaç Türkçe kalır", () => {
    expect(text(createElement(Label))).toBe("tr|Merhaba Dünya");
  });

  it("provider dilini çeviriye verir", () => {
    expect(text(createElement(I18nProvider, { lang: "en" }, createElement(Label)))).toBe("en|Hello World");
  });

  it("desteklenmeyen dil Türkçe'ye düşer", () => {
    expect(text(createElement(I18nProvider, { lang: "de" }, createElement(Label)))).toBe("tr|Merhaba Dünya");
  });
});

describe("t", () => {
  const tOf = (lang) => {
    let captured;
    function Grab() {
      captured = useT().t;
      return null;
    }
    renderToStaticMarkup(createElement(I18nProvider, { lang }, createElement(Grab)));
    return captured;
  };

  it("katalogda olmayan anahtar olduğu gibi döner", () => {
    expect(tOf("en")("olmayan.anahtar")).toBe("olmayan.anahtar");
  });

  it("İngilizce'de olmayan satır Türkçe'sinden okunur", () => {
    expect(tOf("en")("sadece.tr")).toBe("Yalnız Türkçe");
  });

  it("parametreler cümleye yerleşir, verilmeyen olduğu gibi kalır", () => {
    expect(tOf("en")("selam", { name: "World" })).toBe("Hello World");
    expect(tOf("en")("selam")).toBe("Hello {name}");
    expect(tOf("tr")("selam", { ad: 42 })).toBe("Merhaba 42");
  });
});

describe("pickLang", () => {
  it("sıra: kullanıcı > depolanan > tarayıcı > tr", () => {
    expect(pickLang({ me: { lang: "en" }, stored: "tr", navigator: { language: "tr-TR" } })).toBe("en");
    expect(pickLang({ me: null, stored: "en", navigator: { language: "tr-TR" } })).toBe("en");
    expect(pickLang({ stored: "de", navigator: { language: "en-US" } })).toBe("en");
    expect(pickLang({ navigator: { language: "fr-FR" } })).toBe("tr");
    expect(pickLang({})).toBe("tr");
    expect(pickLang()).toBe("tr");
  });

  it("kullanıcının desteklenmeyen dili sıradakine bırakır", () => {
    expect(pickLang({ me: { lang: "de" }, stored: "en" })).toBe("en");
  });
});

describe("loadCatalog", () => {
  it("desteklenen dili yükler, desteklenmeyeni Türkçe'ye çevirir", async () => {
    expect(await loadCatalog("en")).toBe("en");
    expect(await loadCatalog("de")).toBe("tr");
    expect(await loadCatalog("tr")).toBe("tr");
  });
});
