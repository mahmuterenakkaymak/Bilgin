// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// @vitest-environment jsdom
// T441 (R8-20): bağlantı ekranının listesi, formu ve deneme cevabının iki dili. İki dil aynı id
// kümesini boyar; İngilizce kabuk Türkçe harf taşımaz — küme adları, sürücünün hatası ve
// denetimin satırları veridir, çevrilmez, o yüzden İngilizce geçiş İngilizce veriyle yapılır.
// Türkçe çıktı bugünkü cümleleri harfi harfine verir: ConnectionsScreen.test.jsx o cümleleri
// bekliyor. Formun reddi `clientErrors(form, { lang })` arayüzün dilinden okunur; connForm.js'nin
// sabitleri Türkçe katalog değerlerinin kendisidir.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import en from "../i18n/en.json";
import { I18nProvider } from "../i18n/index.js";
import tr from "../i18n/tr.json";
import * as api from "../lib/api.js";
import {
  BAD_AUTH_MESSAGE,
  BAD_PORT_MESSAGE,
  DPAPI_MESSAGE,
  EMPTY_FORM,
  ENV_SOURCE_MESSAGE,
  NO_DATABASE_MESSAGE,
  NO_PASSWORD_MESSAGE,
  NO_SERVER_MESSAGE,
  NO_USERNAME_MESSAGE,
  clientErrors,
} from "../lib/connForm.js";
import ConnectionsScreen from "./ConnectionsScreen.jsx";

vi.mock("../lib/api.js", async (importOriginal) => ({
  ...(await importOriginal()),
  connectionsGet: vi.fn(),
  connectionsSave: vi.fn(),
  connectionsTest: vi.fn(),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const noop = () => {};
const TURKISH = /[çğıöşüÇĞİÖŞÜ]/;

// Sözleşme "connection (public)": satırda ne parola vardır ne bağlantı dizesi. Veriler iki dilde
// aynı ve ASCII — çevrilen tek şey kabuk, o yüzden İngilizce geçişte Türkçe harf kalmamalı.
const ROWS = [
  {
    dataset: "wwi",
    server: "10.0.0.5",
    database: "WWI",
    auth: "sql",
    username: "bilgin_ro",
    options: { encrypt: true, trust_server_certificate: false, port: 1433, driver: "" },
    has_secret: true,
    last_ok_at: "2026-10-27T09:15:00+00:00",
    last_error: null,
    state: "ok",
    source: "stored",
    read_only_form: false,
  },
  {
    dataset: "erp",
    server: "localhost",
    database: "DNAEGITIM",
    auth: "windows",
    username: "",
    options: { encrypt: true, trust_server_certificate: true, port: null, driver: "" },
    has_secret: false,
    last_ok_at: null,
    last_error: "Login failed for user 'EREN\\SQL'.",
    state: "down",
    source: "env_dataset",
    read_only_form: true,
  },
  {
    dataset: "fresh",
    server: "",
    database: "",
    auth: "sql",
    username: "",
    options: { encrypt: true, trust_server_certificate: true, port: null, driver: "" },
    has_secret: false,
    last_ok_at: null,
    last_error: null,
    state: "none",
    source: "none",
    read_only_form: false,
  },
  // Tanınmayan bir yoklama cevabı "Denenmedi"ye düşer: hücre boş ya da ham kod kalmaz.
  {
    dataset: "legacy",
    server: "10.0.0.9",
    database: "LEGACY",
    auth: "sql",
    username: "ro",
    options: { encrypt: true, trust_server_certificate: true, port: null, driver: "" },
    has_secret: true,
    last_ok_at: null,
    last_error: null,
    state: "booting",
    source: "stored",
    read_only_form: false,
  },
];

// Sözleşme "guard report": denetimin satırları sunucunun cevabıdır, çevrilmez.
const REPORT = {
  ok: false,
  lines: [
    { check: "sysadmin", ok: false, message: "This login can write; use a read-only login." },
    { check: "table", ok: true, message: "TBLSTHAR is readable with this login." },
  ],
  missing_tables: ["TBLFATUIRS"],
  login_script_url: "/api/datasets/wwi/login-script.sql",
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
const screen = (lang, props = {}) => inLang(lang, <ConnectionsScreen connections={ROWS} onRefresh={noop} {...props} />);
const row = (html, name) => html.split("<tr").find((chunk) => chunk.includes(`data-conn-edit="${name}"`)) ?? "";

let container;
let root;

async function mount(lang) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () =>
    root.render(
      <I18nProvider lang={lang}>
        <ConnectionsScreen connections={ROWS} onRefresh={noop} />
      </I18nProvider>,
    ),
  );
  await settle();
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
    for (let turn = 0; turn < 10; turn += 1) await Promise.resolve();
  });
}

// React kontrollü girdiye yazmak değeri yerleştirmeyi değil, yerel değiştiriciyi çağırmayı ister.
async function fill(node, value) {
  const setter = Object.getOwnPropertyDescriptor(node.constructor.prototype, "value").set;
  await act(async () => {
    setter.call(node, value);
    node.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await settle();
}

async function click(node) {
  await act(async () => node.click());
  await settle();
}

async function submit(app) {
  await act(async () => {
    app.querySelector("#conn-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  await settle();
}

beforeEach(() => {
  api.connectionsGet.mockImplementation((name) => Promise.resolve(ROWS.find((item) => item.dataset === name) ?? ROWS[0]));
  api.connectionsTest.mockResolvedValue(REPORT);
  api.connectionsSave.mockResolvedValue({ connection: ROWS[0], guard: REPORT });
});

afterEach(() => {
  if (root) unmount();
  vi.restoreAllMocks();
});

describe("bağlantı ekranı iki dilde", () => {
  it("aynı id kümesini boyar: çeviri markup'ı değiştirmez", () => {
    const base = ids(screen("tr"));
    for (const id of ["conn-screen", "conn-form", "conn-server", "conn-password", "conn-test", "conn-save"]) {
      expect(base).toContain(id);
    }
    expect(ids(screen("en"))).toEqual(base);

    for (const props of [{}, { loading: true }, { connections: [] }, { error: "Auth is off." }]) {
      expect(ids(screen("en", props))).toEqual(ids(screen("tr", props)));
    }
  });

  it("İngilizce kabuk Türkçe harf ve bugünün cümlesini taşımıyor", () => {
    const html = screen("en");
    expect(html).not.toMatch(TURKISH);
    for (const text of [
      ">Database connections</h1>",
      ">Dataset</th>",
      ">Status</th>",
      ">Server / database</th>",
      ">Last success</th>",
      ">Last error</th>",
      ">Actions</th>",
      ">From an environment variable</span>",
      ">Connected</td>",
      ">Unreachable</td>",
      ">Not set up</td>",
      ">Not tested</td>",
      ">Connection</h2>",
      ">Server</label>",
      ">Password</label>",
      'placeholder="type to change"',
      ">SQL identity (username and password)</option>",
      ">Windows identity (the server's own account)</option>",
      "Encrypt the connection (Encrypt)",
      "Pick “Edit” in one of the rows above to change it.",
      ">Test connection</button>",
      ">Save</button>",
      ">Edit</button>",
    ]) {
      expect(html).toContain(text);
    }
    for (const text of [
      ">Veritabanı bağlantıları<",
      ">Son başarılı</th>",
      ">Son hata</th>",
      ">Ortam değişkeninden<",
      ">Kimlik doğrulama<",
      ">Bağlantıyı test et<",
      ">Kaydet</button>",
      ">Düzenle</button>",
      'placeholder="değiştirmek için yazın"',
    ]) {
      expect(html).not.toContain(text);
    }

    // Tarih de dilin: "Ekim" İngilizce hücreye sızmaz.
    expect(row(html, "wwi")).toContain("October");
    expect(screen("en", { loading: true, connections: [] })).toContain("Reading connections…");
    expect(screen("en", { connections: [] })).toContain("No dataset is connected to SQL Server");
    expect(screen("en", { connections: [], error: "Auth is off." })).toContain("Connections could not be read.");
    // Sunucunun reddi kendi cümlesiyle durur; çevrilen tek şey kabuktur.
    expect(screen("en", { error: "Login failed for user 'EREN\\SQL'." })).toContain("Login failed for user");
  });

  it("Türkçe ekran bugünkü cümleleri harfi harfine veriyor ve provider'sız haliyle aynı", () => {
    const html = screen("tr");
    expect(render(<ConnectionsScreen connections={ROWS} onRefresh={noop} />)).toBe(html);
    for (const text of [
      ">Veritabanı bağlantıları</h1>",
      ">Veri kümesi</th>",
      ">Durum</th>",
      ">Sunucu / veritabanı</th>",
      ">Son başarılı</th>",
      ">Son hata</th>",
      ">İşlemler</th>",
      ">Ortam değişkeninden</span>",
      ">Bağlı</td>",
      ">Erişilemiyor</td>",
      ">Kurulu değil</td>",
      ">Denenmedi</td>",
      ">Bağlantı</h2>",
      ">Sunucu</label>",
      ">Parola</label>",
      'placeholder="değiştirmek için yazın"',
      ">SQL kimliği (kullanıcı adı ve parola)</option>",
      "Bağlantıyı şifrele (Encrypt)",
      "Düzenlemek için yukarıdaki bir satırdan “Düzenle”yi seçin.",
      ">Bağlantıyı test et</button>",
      ">Kaydet</button>",
      ">Düzenle</button>",
    ]) {
      expect(html).toContain(text);
    }
    expect(row(html, "wwi")).toContain("Ekim 2026");
    expect(screen("tr", { loading: true, connections: [] })).toContain("Bağlantılar okunuyor…");
    expect(screen("tr", { connections: [] })).toContain("SQL Server'a bağlı veri kümesi yok");
    expect(screen("tr", { connections: [], error: "Kimlik doğrulama kapalı." })).toContain("Bağlantılar okunamadı.");
  });
});

describe("formun reddi ve denemenin cevabı iki dilde", () => {
  it("satırın başlığı, eksik alanın cümlesi ve denetimin kabuğu arayüzün dilinde", async () => {
    for (const lang of ["tr", "en"]) {
      api.connectionsTest.mockClear();
      const app = await mount(lang);
      await click(app.querySelector('[data-conn-edit="wwi"]'));
      expect(app.querySelector("h2").textContent).toBe(lang === "tr" ? "Bağlantı · wwi" : "Connection · wwi");
      expect(app.querySelector("#conn-password").getAttribute("placeholder")).toBe(
        lang === "tr" ? "değiştirmek için yazın" : "type to change",
      );

      await fill(app.querySelector("#conn-server"), "");
      await click(app.querySelector("#conn-test"));
      expect(api.connectionsTest).not.toHaveBeenCalled();
      expect(app.querySelector("#conn-server-note").textContent).toBe(
        lang === "tr" ? NO_SERVER_MESSAGE : en["conn.form.server"],
      );

      await fill(app.querySelector("#conn-server"), "10.0.0.5");
      await click(app.querySelector("#conn-test"));
      const result = app.querySelector("#conn-result");
      expect(result.textContent).toContain(
        lang === "tr" ? "Bu giriş kaydedilemez — aşağıdaki denetimler düştü." : "This login cannot be saved",
      );
      expect(result.textContent).toContain("✗");
      // Denetimin satırları veridir: iki dilde de sunucunun yazdığı okunur.
      expect(result.textContent).toContain("This login can write; use a read-only login.");
      expect(app.querySelector("#conn-missing").textContent).toBe(
        lang === "tr" ? "Bu girişle okunamayan tablolar: TBLFATUIRS." : "Tables this login cannot read: TBLFATUIRS.",
      );
      expect(app.querySelector("#conn-login-script").textContent).toBe(
        lang === "tr" ? "Salt okunur giriş betiğini indir" : "Download the read-only login script",
      );
      unmount();
    }
  });

  it("saklı sırrı olmayan satırda parolanın cümlesi ve kaydetmenin cevabı iki dilde", async () => {
    for (const lang of ["tr", "en"]) {
      api.connectionsSave.mockClear();
      const app = await mount(lang);
      await click(app.querySelector('[data-conn-edit="fresh"]'));
      await fill(app.querySelector("#conn-server"), "10.0.0.9");
      await fill(app.querySelector("#conn-database"), "FRESH");
      await fill(app.querySelector("#conn-username"), "ro");
      await submit(app);
      expect(api.connectionsSave).not.toHaveBeenCalled();
      expect(app.querySelector("#conn-password-note").textContent).toBe(
        lang === "tr" ? NO_PASSWORD_MESSAGE : en["conn.form.password"],
      );

      await fill(app.querySelector("#conn-password"), "Uzun-Parola-10");
      await submit(app);
      expect(api.connectionsSave).toHaveBeenCalled();
      expect(app.querySelector("#conn-note").textContent).toBe(
        lang === "tr" ? "Bağlantı kaydedildi." : "The connection was saved.",
      );
      unmount();
    }
  });

  it("ortam değişkeninin bandı iki dilde okunuyor ve alanları kapatıyor", async () => {
    for (const lang of ["tr", "en"]) {
      const app = await mount(lang);
      await click(app.querySelector('[data-conn-edit="erp"]'));
      expect(app.querySelector("#conn-readonly").textContent).toBe(
        lang === "tr" ? ENV_SOURCE_MESSAGE : en["conn.readonly"],
      );
      expect(app.querySelector("#conn-server").disabled).toBe(true);
      expect(app.querySelector("#conn-save").disabled).toBe(true);
      unmount();
    }
  });

  // Sunucu 409'u arayüzün dilinde veriyor: parolayı saklayamayan sunucunun cümlesi kataloğun
  // kendi satırıyla tanınmazsa form bir daha sır sorar ve yönetici aynı reddi tekrar dener.
  it("parolayı saklayamayan sunucunun reddi iki dilde de tanınıyor", async () => {
    for (const lang of ["tr", "en"]) {
      const refusal = lang === "tr" ? DPAPI_MESSAGE : en["conn.dpapiOff"];
      api.connectionsSave.mockRejectedValue({ status: 409, message: refusal });
      const app = await mount(lang);
      await click(app.querySelector('[data-conn-edit="wwi"]'));
      expect(app.querySelector("#conn-password").disabled).toBe(false);
      await submit(app);
      expect(app.querySelector("#conn-error").textContent).toBe(refusal);
      expect(app.querySelector("#conn-password").disabled).toBe(true);
      expect(app.querySelector("#conn-save").disabled).toBe(true);
      unmount();
    }
  });
});

describe("reddin cümlesi iki yerde yazılmıyor", () => {
  it("connForm'un sabitleri Türkçe katalog değerlerinin kendisidir", () => {
    expect(NO_SERVER_MESSAGE).toBe(tr["conn.form.server"]);
    expect(NO_DATABASE_MESSAGE).toBe(tr["conn.form.database"]);
    expect(BAD_AUTH_MESSAGE).toBe(tr["conn.form.auth"]);
    expect(NO_USERNAME_MESSAGE).toBe(tr["conn.form.username"]);
    expect(NO_PASSWORD_MESSAGE).toBe(tr["conn.form.password"]);
    expect(BAD_PORT_MESSAGE).toBe(tr["conn.form.port"]);
    expect(ENV_SOURCE_MESSAGE).toBe(tr["conn.readonly"]);
    expect(DPAPI_MESSAGE).toBe(tr["conn.dpapiOff"]);
    // Formun dili seçenek nesnesinden okunur: İngilizce boş form İngilizce red üretir.
    expect(clientErrors(EMPTY_FORM, { lang: "en" }).server).toBe(en["conn.form.server"]);
    expect(clientErrors(EMPTY_FORM).server).toBe(NO_SERVER_MESSAGE);
  });
});
