// @vitest-environment jsdom
// T482: Run 8 altı bağlantıyı telefonun kaydırdığı sıraya çağırdı ve 1366'da maske "Hazır sor"u
// yuttu — bir ekran ulaşılmaz görünüyordu. Adlar kısaldı, tam ad `title` ile erişim adına taşındı:
// kısalığın ölçüsü kataloğun kendisinde, gittiği yerin adı ise bağlantının verdiği adda okunur.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import en from "../i18n/en.json";
import tr from "../i18n/tr.json";
import { I18nProvider } from "../i18n/index.js";
import MastheadNav from "./MastheadNav.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const TURKISH = /[çğıöşüÇĞİÖŞÜ]/;
const ADMIN = { username: "admin", role: "admin" };
const LINKS = ["ask", "rules", "map", "connections", "ready", "users"];
const LANGS = [
  ["tr", tr],
  ["en", en],
];

describe("gezinme adları katalogda kısa", () => {
  for (const [lang, catalog] of LANGS) {
    const navKeys = Object.keys(catalog).filter((key) => key.startsWith("nav."));

    it(`${lang} kataloğunda gezinme adı 12 karakteri geçmiyor`, () => {
      expect(navKeys.length).toBeGreaterThan(0);
      const long = navKeys.filter((key) => catalog[key].length > 12).map((key) => `${key}: ${catalog[key]}`);
      expect(long).toEqual([]);
    });
  }

  it("İngilizce gezinme adında Türkçe harf kalmıyor", () => {
    const dirty = Object.keys(en)
      .filter((key) => key.startsWith("nav.") && TURKISH.test(en[key]))
      .map((key) => `${key}: ${en[key]}`);
    expect(dirty).toEqual([]);
  });
});

describe("bağlantının kendi adı tam cümle", () => {
  let container;
  let root;

  function renderNav(lang) {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    act(() =>
      root.render(
        <I18nProvider lang={lang}>
          <MastheadNav route="ask" user={ADMIN} />
        </I18nProvider>,
      ),
    );
    return container;
  }

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  for (const [lang, catalog] of LANGS) {
    it(`${lang} bağlantısının metni kısa ad, title ve erişim adı tam cümle`, () => {
      const el = renderNav(lang);
      for (const name of LINKS) {
        const link = el.querySelector(`#nav-${name}`);
        expect(link.textContent).toBe(catalog[`nav.${name}`]);
        expect(link.getAttribute("title")).toBe(catalog[`navfull.${name}`]);
        expect(link.getAttribute("aria-label")).toBe(catalog[`navfull.${name}`]);
      }
    });
  }
});
