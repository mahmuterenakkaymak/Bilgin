// @vitest-environment jsdom
// Kart ilk gelene ne açtığını söylemeli: etiketin cümlesi, formun iki alanı ve reddedilen
// girişin yazılanı koruması burada okunur. Ağ işi Root'un, bileşen yalnız onLogin'i bekler —
// o yüzden testin sahtesi bir söz vermeden ibaret, kartın kendisi hiçbir adrese çıkmaz.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import LoginScreen from "./LoginScreen.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const TAGLINE = "Veritabanınıza Türkçe soru sorun; SQL'i Bilgin yazar.";
const EXPIRED = "Oturumunuz sona erdi, lütfen yeniden giriş yapın.";
const DECLINED = "Kullanıcı adı ya da parola hatalı.";
const noop = () => {};

// Cümlelerdeki kesme işareti ve tırnak SSR çıktısında düz karakter değildir; okunur metin öyle aranır.
function render(element) {
  return renderToStaticMarkup(element)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&");
}

const tagline = (html) => /class="login-tagline"[^>]*>([^<]*)</.exec(html)?.[1] ?? "";
const count = (html, needle) => html.split(needle).length - 1;

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

afterEach(() => {
  if (root) {
    act(() => root.unmount());
    root = undefined;
  }
  container?.remove();
  container = undefined;
  vi.clearAllMocks();
});

describe("giriş kartının etiketi", () => {
  it("cümlenin altında dolu bir etiket satırı var", () => {
    const html = render(<LoginScreen onLogin={noop} />);
    expect(tagline(html).trim()).toBe(TAGLINE);
    // Sıra: çağrı cümlesi, onun altında etiket, onların altında alanlar.
    expect(html.indexOf("login-lead")).toBeLessThan(html.indexOf("login-tagline"));
    expect(html.indexOf("login-tagline")).toBeLessThan(html.indexOf("login-username"));
  });

  it("kartın tepesinde ürünün kendi işareti var: bir kez, boş alt ile adın üstünde", () => {
    const html = render(<LoginScreen onLogin={noop} />);
    const marks = html.match(/<img\b[^>]*>/g) ?? [];
    expect(marks).toHaveLength(1);
    expect(marks[0]).toContain('src="/assets/bilgin.svg"');
    expect(marks[0]).toContain('alt=""');
    expect(html.indexOf("<img")).toBeLessThan(html.indexOf('class="login-title"'));
  });

  it("etiket sabittir: not gelse de değişmez, veri seti ya da adres adı taşımaz", () => {
    expect(tagline(render(<LoginScreen note={EXPIRED} onLogin={noop} />))).toBe(TAGLINE);
    expect(tagline(render(<LoginScreen onLogin={noop} />))).not.toMatch(/http|«|\.db|veri seti/i);
  });

  it("formun iki alanı bir gönderme düğmesi var, sırası bozulmadı", () => {
    const html = render(<LoginScreen onLogin={noop} />);
    expect(count(html, "<input")).toBe(2);
    expect(count(html, 'type="submit"')).toBe(1);
    expect(html.indexOf("login-username")).toBeLessThan(html.indexOf("login-password"));
    expect(html.indexOf("login-password")).toBeLessThan(html.indexOf("login-submit"));
  });
});

describe("reddedilen giriş", () => {
  it("yazılan kullanıcı adı kartta kalır, düğme yeniden basılabilir", async () => {
    const onLogin = vi.fn(() => Promise.reject(new Error(DECLINED)));
    const app = await mount(<LoginScreen onLogin={onLogin} />);

    await fill(app.querySelector("#login-username"), "eren");
    await fill(app.querySelector("#login-password"), "gizli-parola");
    await click(app.querySelector("#login-submit"));
    await settle();

    expect(onLogin).toHaveBeenCalledWith({ username: "eren", password: "gizli-parola" });
    expect(app.querySelector("#login-username").value).toBe("eren");
    expect(app.querySelector("#login-error").textContent).toBe(DECLINED);
    expect(app.querySelector("#login-submit").disabled).toBe(false);
  });
});
