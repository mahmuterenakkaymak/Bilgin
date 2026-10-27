// @vitest-environment jsdom
// T439 (R8-20): kullanıcı defterinin, ekleme formunun ve kendi satırının iki dili. İki dil aynı
// id kümesini boyar; İngilizce kabuk Türkçe harf taşımaz — hesap adları, rollerin kodları ve
// sunucunun reddi veridir, çevrilmez, o yüzden İngilizce geçiş İngilizce veriyle yapılır. Türkçe
// çıktı bugünkü cümleleri harfi harfine verir: UsersScreen.test.jsx, UsersScreenSelfRow.test.jsx
// ve UsersBusinessRole.test.jsx o cümleleri bekliyor. Formun reddi `clientErrors(form, lang)`
// arayüzün dilinden okunur; usersForm.js'nin dört sabiti Türkçe katalog değerlerinin kendisidir.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import en from "../i18n/en.json";
import { I18nProvider } from "../i18n/index.js";
import tr from "../i18n/tr.json";
import * as api from "../lib/api.js";
import { MATCH_MESSAGE, NAME_MESSAGE, PASSWORD_MESSAGE, ROLE_MESSAGE } from "../lib/usersForm.js";
import UsersScreen from "./UsersScreen.jsx";

vi.mock("../lib/api.js", async (importOriginal) => ({
  ...(await importOriginal()),
  usersCreate: vi.fn(async (body) => body),
  usersUpdate: vi.fn(async () => ({})),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const noop = () => {};
const TURKISH = /[çğıöşüÇĞİÖŞÜ]/;

// Satırlar iki dilde aynı: ad ve tarih veridir, iş rolünün kodu katalogdan okunur.
const USERS = [
  {
    id: 1,
    username: "admin",
    role: "admin",
    business_role: "yonetim",
    active: true,
    created_at: "2026-10-20T09:00:00+00:00",
    last_login_at: "2026-10-26T08:15:00+00:00",
  },
  {
    id: 2,
    username: "analyst",
    role: "user",
    business_role: "satis",
    active: false,
    created_at: "2026-10-21T09:00:00+00:00",
    last_login_at: null,
  },
];

// /api/auth/me'nin sözleşme {username, role, business_role}: kendi satırı addan çözülüyor.
const ME = { username: "admin", role: "admin", business_role: "yonetim" };

// Sunucunun reddi kendi diliyle gelir — çevrilmez.
const REFUSAL = "Bu kullanıcı adı zaten var.";

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
const screen = (lang, props = {}) => inLang(lang, <UsersScreen users={USERS} onRefresh={noop} {...props} />);
const row = (html, id) => html.split("<tr").find((chunk) => chunk.includes(`data-user-role="${id}"`)) ?? "";

let container;
let root;

async function mount(lang) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(<I18nProvider lang={lang}>{shell()}</I18nProvider>));
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

// Kontrollü girdi: React'ın değer izleyicisini dolaşmak için yerleşik setter'a yazılır.
function type(node, value) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
  setter.call(node, value);
  node.dispatchEvent(new Event("input", { bubbles: true }));
}

async function pick(node, value) {
  await act(async () => {
    node.value = value;
    node.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await settle();
}

async function submit(app) {
  await act(async () => {
    app.querySelector("#user-add-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  await settle();
}

afterEach(() => {
  if (root) unmount();
  vi.restoreAllMocks();
});

describe("kullanıcı defteri iki dilde", () => {
  it("aynı id kümesini boyar: çeviri markup'ı değiştirmez", () => {
    const base = ids(screen("tr"));
    expect(base).toContain("users-screen");
    expect(base).toContain("user-add-form");
    expect(base).toContain("user-new-business-role");
    expect(ids(screen("en"))).toEqual(base);

    for (const props of [{}, { currentUser: ME }, { error: REFUSAL }, { users: [], loading: true }]) {
      expect(ids(screen("en", props))).toEqual(ids(screen("tr", props)));
    }
  });

  it("İngilizce kabuk Türkçe harf ve bugünün cümlesini taşımıyor", () => {
    const html = screen("en");
    expect(html).not.toMatch(TURKISH);
    for (const text of [
      ">Users</h1>",
      ">New user</h2>",
      ">Username</label>",
      ">Password (repeat)</label>",
      ">Business role</th>",
      ">Last sign-in</th>",
      ">Actions</th>",
      ">Active</span>",
      ">Passive</span>",
      ">Deactivate</button>",
      ">Change password</button>",
      ">Add user</button>",
      'aria-label="analyst role"',
      "Never signed in.",
    ]) {
      expect(html).toContain(text);
    }
    for (const text of [
      ">Kullanıcılar<",
      ">Yeni kullanıcı<",
      ">İş rolü</th>",
      ">İşlemler</th>",
      ">Pasifleştir</button>",
      ">Parolayı değiştir</button>",
      ">Kullanıcıyı ekle</button>",
    ]) {
      expect(html).not.toContain(text);
    }

    expect(screen("en", { users: [], loading: true })).toContain("Reading users…");
    expect(screen("en", { users: [] })).toContain("No users yet.");
    expect(screen("en", { users: [], error: REFUSAL })).toContain("Users could not be read.");
    // Sunucunun reddi kendi cümlesiyle durur; çevrilen tek şey kabuktur.
    expect(screen("en", { error: REFUSAL })).toContain(REFUSAL);
  });

  it("Türkçe ekran bugünkü cümleleri harfi harfine veriyor ve provider'sız haliyle aynı", () => {
    const html = screen("tr");
    expect(render(<UsersScreen users={USERS} onRefresh={noop} />)).toBe(html);
    for (const text of [
      ">Kullanıcılar</h1>",
      ">Yeni kullanıcı</h2>",
      ">Kullanıcı adı</label>",
      ">Parola (tekrar)</label>",
      ">İş rolü</th>",
      ">Son giriş</th>",
      ">İşlemler</th>",
      ">Etkin</span>",
      ">Pasif</span>",
      ">Pasifleştir</button>",
      ">Etkinleştir</button>",
      ">Parolayı değiştir</button>",
      ">Kullanıcıyı ekle</button>",
      'aria-label="analyst rolü"',
      "Hiç giriş yapmadı.",
      "Yönetici kullanıcıları ve iş kurallarını değiştirir.",
    ]) {
      expect(html).toContain(text);
    }
    expect(screen("tr", { users: [], loading: true })).toContain("Kullanıcılar okunuyor…");
    expect(screen("tr", { users: [] })).toContain("Henüz kullanıcı yok.");
    expect(screen("tr", { users: [], error: REFUSAL })).toContain("Kullanıcılar okunamadı.");
  });

  it("rol ve iş rolü adları iki dilde katalogdan okunuyor", () => {
    expect(screen("tr")).toContain(">Yönetici</option>");
    expect(screen("en")).toContain(">Admin</option>");
    expect(screen("tr")).toContain(">Satın alma</option>");
    expect(screen("en")).toContain(">Purchasing</option>");
    expect(screen("tr")).toContain(">Yönetim</option>");
    expect(screen("en")).toContain(">Management</option>");
  });

  it("kendi satırının iş rolü kapalı ve nedeni iki dilde başlığında", () => {
    expect(screen("tr", { currentUser: ME })).toContain('title="Kendi iş rolünüzü değiştiremezsiniz."');
    const own = screen("en", { currentUser: ME });
    expect(own).toContain('title="You cannot change your own business role."');
    expect(own).not.toMatch(TURKISH);
    // Öteki satırda başlık yok: alan açık, nedeni de yok.
    expect(row(screen("en", { currentUser: ME }), 2)).not.toContain("You cannot change");
  });
});

describe("ekleme formunun reddi iki dilde", () => {
  it("boş formun alan hataları arayüzün dilinde okunuyor", async () => {
    for (const lang of ["tr", "en"]) {
      const app = await mount(lang);
      expect(app.querySelector("#user-new-username-note").className).toBe("field-hint");
      await submit(app);
      expect(app.querySelector("#user-new-username-note").textContent).toBe(
        lang === "tr" ? NAME_MESSAGE : "Username must be 3-32 characters and may contain only lowercase letters, digits, . _ -.",
      );
      expect(app.querySelector("#user-new-password-note").textContent).toBe(
        lang === "tr" ? PASSWORD_MESSAGE : "Password must be at least 10 characters.",
      );
      expect(app.querySelector("#user-new-password2-note").className).toBe("field-hint");
      unmount();
    }
  });

  it("eşleşmeyen tekrarın cümlesi dilin cümlesi, sunucunun reddi olduğu gibi", async () => {
    for (const lang of ["tr", "en"]) {
      const app = await mount(lang);
      type(app.querySelector("#user-new-username"), "analyst9");
      type(app.querySelector("#user-new-password"), "Uzun-Parola-10");
      type(app.querySelector("#user-new-password2"), "Baska-Parola-1");
      await submit(app);
      expect(app.querySelector("#user-new-password2-note").textContent).toBe(
        lang === "tr" ? MATCH_MESSAGE : "The passwords do not match.",
      );
      expect(app.querySelector("#user-new-username-note").className).toBe("field-hint");
      unmount();
    }

    api.usersCreate.mockRejectedValueOnce({ message: REFUSAL });
    const app = await mount("en");
    type(app.querySelector("#user-new-username"), "analyst9");
    type(app.querySelector("#user-new-password"), "Uzun-Parola-10");
    type(app.querySelector("#user-new-password2"), "Uzun-Parola-10");
    await submit(app);
    expect(app.querySelector("#users-error").textContent).toBe(REFUSAL);
    expect(app.querySelector("#user-new-username").getAttribute("aria-invalid")).toBe("true");
  });

  it("kendi rolü sorusu ve değişikliğin cevabı iki dilde okunuyor", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    for (const lang of ["tr", "en"]) {
      const app = await mount(lang);
      await pick(app.querySelector('[data-user-role="1"]'), "user");
      expect(confirm).toHaveBeenLastCalledWith(
        lang === "tr"
          ? "Kendi rolünüzü değiştiriyorsunuz; yönetici ekranları kapanır. Değiştirilsin mi?"
          : "You are changing your own role; admin screens will close. Change it?",
      );
      expect(api.usersUpdate).not.toHaveBeenCalled();
      unmount();
    }

    confirm.mockReturnValue(true);
    const app = await mount("en");
    await pick(app.querySelector('[data-user-role="2"]'), "admin");
    expect(app.textContent).toContain("The role of “analyst” was updated.");
    await pick(app.querySelector('[data-user-business-role="2"]'), "muhasebe");
    expect(app.textContent).toContain("The business role of “analyst” was updated.");
  });
});

describe("reddin cümlesi iki yerde yazılmıyor", () => {
  it("usersForm'un dört sabiti Türkçe katalog değerlerinin kendisidir", () => {
    expect(NAME_MESSAGE).toBe(tr["users.form.username"]);
    expect(PASSWORD_MESSAGE).toBe(tr["users.form.password"].replace("{min}", "10"));
    expect(MATCH_MESSAGE).toBe(tr["users.form.password2"]);
    expect(ROLE_MESSAGE).toBe(tr["users.form.role"]);
    expect(en["users.form.password"]).toContain("{min}");
  });
});

function shell() {
  return <UsersScreen users={USERS} currentUser={ME} onRefresh={noop} />;
}
