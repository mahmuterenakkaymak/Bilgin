// @vitest-environment jsdom
// T481: İngilizce arayüzün ekrana gerçekten ulaşıp ulaşmadığı. test-setup iki kataloğu da kayıtlı
// getirdiği için hiçbir i18n testi "uygulama İngilizce kataloğu hiç indirmiyor" gerçeğini
// göremez; burası EN kataloğunu boş kaydedip açılışı Türkçe'ye düşürür ve dil düğmesinin o
// kataloğu gerçekten indirip indirmediğini giriş kartının cümlelerinden okur.
// ASSUMPTION: "App logged out" oturum kapısının kart halidir — LoginScreen App'in değil Root'un
// içinde yaşıyor (M28'in en-login kareleri de kartı gösteriyor), o yüzden ağaç Root ile kuruluyor.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Root from "../Root.jsx";
import { I18nProvider, registerCatalog, useT } from "./index.js";

// Kataloğun inmemesi bir ağ hatasıdır ve tek gerçek yolu indirmenin kendisinin reddedilmesidir.
const chunk = vi.hoisted(() => ({ fails: false }));

// İndirmenin reddi bir kereye mahsus simüle edilemez: vitest mock'un cevabını dosya boyunca
// saklıyor. O yüzden chunk'ın KENDİSİ geliyor, ama içeriğe erişim ağ hatası gibi patlıyor —
// loadCatalog tam o erişimde reddediliyor.
vi.mock("./en.json", async () => {
  const actual = await vi.importActual("./en.json");
  return {
    get default() {
      if (chunk.fails) throw new Error("en chunk'ı inemedi");
      return actual.default;
    },
  };
});

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const LOGIN = { screen: "login", user: null, requested: "#/", note: "" };
const LEAD_TR = "Sormaya devam etmek için oturum açın.";
const LEAD_EN = "Sign in to keep asking.";

// Provider'ın dili: kartın kendi cümleleri çevrilse de dilin kendisi buradan okunur.
function LangProbe() {
  const { lang } = useT();
  return <span id="lang-probe">{lang}</span>;
}

let container;
let root;

// Katalog indirmesi gerçek bir modül sözü: boyama onun haberiyle geliyor, o yüzden birden çok
// tur bekleniyor.
async function settle() {
  await act(async () => {
    for (let i = 0; i < 20; i += 1) await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function mountTurkishBoot() {
  registerCatalog("en", {}); // Türkçe açılış: İngilizce kataloğu henüz inmemiş
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <I18nProvider lang="tr">
        <Root initial={LOGIN} />
        <LangProbe />
      </I18nProvider>,
    );
  });
  return container;
}

async function pickEnglish(app) {
  await act(async () => {
    app.querySelector('#lang-toggle button[data-lang="en"]').dispatchEvent(
      new MouseEvent("click", { bubbles: true, cancelable: true }),
    );
  });
  await settle();
}

beforeEach(() => {
  chunk.fails = false;
});

afterEach(() => {
  act(() => root.unmount());
  container?.remove();
  container = undefined;
  root = undefined;
});

describe("katalog yükleme", () => {
  it("EN'e basmak kataloğu indirir: kart İngilizce boyanır, dil en olur", async () => {
    const app = await mountTurkishBoot();
    expect(app.querySelector(".login-lead").textContent).toBe(LEAD_TR);

    await pickEnglish(app);

    expect(app.querySelector(".login-lead").textContent).toBe(LEAD_EN);
    expect(app.querySelector("#login-submit").textContent).toBe("Sign in");
    expect(app.querySelector("#lang-probe").textContent).toBe("en");
  });

  it("kataloğu inmeyen dil ekrana anahtar taşımaz: Türkçe kalır", async () => {
    chunk.fails = true;
    const app = await mountTurkishBoot();

    await pickEnglish(app);

    expect(app.querySelector(".login-lead").textContent).toBe(LEAD_TR);
    expect(app.querySelector("#login-submit").textContent).toBe("Giriş");
    expect(app.textContent).not.toContain("login.");
    expect(app.querySelector("#lang-probe").textContent).toBe("tr");
  });
});
