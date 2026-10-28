// T445: İngilizce bir kişinin kabuğu başlıkla sınırlı değil. AppShell.i18n.test.jsx başlığın
// temizliğini ölçüyor; burası App'in tamamını ölçüyor - çekmece, pano ve soru kutusu da Türkçe
// harf taşımamalı. Dil, kişinin kendi tercihi: main.jsx `me.lang`den çözdüğünü provider'a veriyor.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import App from "./App.jsx";
import { I18nProvider } from "./i18n/index.js";

const TURKISH = /[çğıöşüÇĞİÖŞÜ]/;
const EN_USER = { username: "eren", role: "admin", business_role: "genel", lang: "en" };
const noop = () => {};

const shell = () =>
  renderToStaticMarkup(
    <I18nProvider lang={EN_USER.lang}>
      <App user={EN_USER} onLogout={noop} />
    </I18nProvider>,
  );

describe("ingilizce kişinin kabuğu", () => {
  it("Türkçe harf taşımıyor", () => {
    expect(shell()).not.toMatch(TURKISH);
  });

  it("gövdesi de çevrili: çekmece, soru kutusu ve çıkış İngilizce", () => {
    const html = shell();
    for (const text of [
      ">Sign out</button>",
      ">Saved and history</button>",
      ">Saved questions</h2>",
      ">No conversations yet.<",
      'placeholder="Write your question"',
      ">Press Enter to send, Shift+Enter for a new line.<",
    ]) {
      expect(html).toContain(text);
    }
  });
});
