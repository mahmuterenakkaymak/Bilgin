// Ekran SSR ile kuruluyor: tablonun işareti (hangi satırda hangi nokta, hangi satır okunur) boya
// çıkmadan da okunur. Olaylar — satırı açmak, denemek, kaydetmek — ağ ister; onların karşılığı
// sunucu tarafında (tests/test_web_connections_api.py) zaten koşuluyor, burada yalnız cevabın
// ekranda ne yazdığı var.
// ASSUMPTION: akışın kurulduğu son blok için ortam jsdom — tıklama ve kontrol edilen girdi orada.
// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../lib/api.js";
import { DPAPI_MESSAGE, ENV_SOURCE_MESSAGE } from "../lib/connForm.js";
import ConnectionsScreen from "./ConnectionsScreen.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../lib/api.js", async (importOriginal) => ({
  ...(await importOriginal()),
  connectionsList: vi.fn(),
  connectionsGet: vi.fn(),
  connectionsSave: vi.fn(),
  connectionsTest: vi.fn(),
}));

const noop = () => {};

function render(element) {
  return renderToStaticMarkup(element)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&");
}

const screen = (props) => render(<ConnectionsScreen onRefresh={noop} {...props} />);

// Sözleşme "connection (public)": satırda ne parola vardır ne bağlantı dizesi.
const ROWS = [
  {
    dataset: "wwi_real",
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
    dataset: "yeni",
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
];

// Sözleşme "guard report": bir denetimi düşmüş, bir tablosu okunamayan giriş.
const REPORT = {
  ok: false,
  lines: [
    { check: "sysadmin", ok: false, message: "Bu giriş yazabiliyor ya da yönetebiliyor; salt okunur bir giriş kullanın." },
    { check: "table", ok: true, message: "TBLSTHAR bu girişle okunabiliyor." },
  ],
  missing_tables: ["TBLFATUIRS"],
  login_script_url: "/api/datasets/wwi_real/login-script.sql",
};

// Satır kendi küme adından bulunur: sütun sırası değişse de ölçüm satıra bakar.
function row(html, name) {
  return html.split("<tr").find((chunk) => chunk.includes(`data-conn-edit="${name}"`)) ?? "";
}

describe("ConnectionsScreen — tablo", () => {
  it("başlığı, altı sütun adını ve formu kurar", () => {
    const html = screen({ connections: ROWS });
    expect(html).toContain('id="conn-screen"');
    expect(html).toContain(">Veritabanı bağlantıları</h1>");
    for (const column of ["Veri kümesi", "Durum", "Sunucu / veritabanı", "Son başarılı", "Son hata", "İşlemler"]) {
      expect(html).toContain(`>${column}</th>`);
    }
    for (const id of [
      "conn-server",
      "conn-database",
      "conn-auth",
      "conn-username",
      "conn-password",
      "conn-encrypt",
      "conn-trust",
      "conn-test",
      "conn-save",
    ]) {
      expect(html).toContain(`id="${id}"`);
    }
  });

  it("parola alanı yazılmaz ve okunmaz: tipi parola, yeri boş, ipucusu değiştirme sözü", () => {
    const html = screen({ connections: ROWS });
    const field = html.slice(html.indexOf('id="conn-password"'));
    expect(field.slice(0, 400)).toContain('type="password"');
    expect(field.slice(0, 400)).toContain('placeholder="değiştirmek için yazın"');
    expect(field.slice(0, 400)).toContain('value=""');
  });

  it("durum noktası satırın kendi yoklamasını taşır, sözcüğü de yanındadır", () => {
    const html = screen({ connections: ROWS });
    expect(row(html, "wwi_real")).toContain('class="db-dot db-dot-ok"');
    expect(row(html, "wwi_real")).toContain("Bağlı</td>");
    expect(row(html, "erp")).toContain('class="db-dot db-dot-down"');
    expect(row(html, "erp")).toContain("Erişilemiyor");
    expect(row(html, "yeni")).toContain('class="db-dot db-dot-none"');
  });

  it("Son başarılı okunur saat; olmayan tarih '—', Son hata sürücünün kendi cümlesi", () => {
    const html = screen({ connections: ROWS });
    expect(row(html, "wwi_real")).toContain("2026");
    expect(row(html, "wwi_real")).toContain(">—</td>");
    expect(row(html, "erp")).toContain("Login failed for user");
    expect(row(html, "erp")).toContain(">—</td>");
  });

  it("'Ortam değişkeninden' çipi yalnız ortam değişkeninin kazandığı satırdadır", () => {
    const html = screen({ connections: ROWS });
    expect(row(html, "erp")).toContain(">Ortam değişkeninden</span>");
    expect(row(html, "wwi_real")).not.toContain("Ortam değişkeninden");
  });

  it("her satırın kendi düzenleme düğmesi vardır", () => {
    const html = screen({ connections: ROWS });
    for (const name of ["wwi_real", "erp", "yeni"]) {
      expect(html).toContain(`data-conn-edit="${name}"`);
    }
    expect(row(html, "wwi_real")).toContain(">Düzenle</button>");
  });

  it("boş, okunan ve düşmüş haller ayrılır; okuma düşünce hücre söz vermez", () => {
    expect(screen({ connections: [], loading: true })).toContain("Bağlantılar okunuyor…");
    const empty = screen({ connections: [] });
    expect(empty).toContain("SQL Server'a bağlı veri kümesi yok");
    expect(empty).not.toContain("okunuyor…");
    const failed = screen({ connections: [], loading: true, error: "Kimlik doğrulama kapalı." });
    expect(failed).toContain('id="conn-error"');
    expect(failed).toContain("Kimlik doğrulama kapalı.");
    expect(failed).not.toContain("okunuyor…");
  });

  it("alanı eksik satır ekranı bozmaz, açılmamış forma ipucu düşer", () => {
    const html = screen({ connections: [null, {}, ROWS[0]] });
    expect(html).not.toMatch(/undefined|null/);
    expect(html).toContain('id="conn-hint"');
    expect(html).toContain("Düzenle");
  });
});

// ---------------------------------------------------------------- jsdom akışı

let container;
let root;

const settle = async () => {
  await act(async () => {
    for (let turn = 0; turn < 10; turn += 1) await Promise.resolve();
  });
};

async function mount(props = {}) {
  await act(async () => root.render(<ConnectionsScreen connections={ROWS} onRefresh={noop} {...props} />));
  await settle();
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

// Kutuyu asıl tıklatmak işi jsdom'a bırakır: işaret kendi değişir, React onChange'ı ondan okur.
async function toggle(node) {
  await act(async () => node.click());
  await settle();
}

async function click(node) {
  await act(async () => node.click());
  await settle();
}

async function submit() {
  await act(async () => {
    container.querySelector("#conn-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  await settle();
}

beforeEach(() => {
  vi.clearAllMocks();
  api.connectionsGet.mockResolvedValue(ROWS[0]);
  api.connectionsTest.mockResolvedValue(REPORT);
  api.connectionsSave.mockResolvedValue({ connection: ROWS[0], guard: REPORT });
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("ConnectionsScreen — satırı açmak", () => {
  it("düzenleme satırı sunucudan okur ve formu doldurur", async () => {
    await mount();
    await click(container.querySelector('[data-conn-edit="wwi_real"]'));
    expect(api.connectionsGet).toHaveBeenCalledWith("wwi_real");
    expect(container.querySelector("#conn-server").value).toBe("10.0.0.5");
    expect(container.querySelector("#conn-database").value).toBe("WWI");
    expect(container.querySelector("#conn-username").value).toBe("bilgin_ro");
    // Parola hiçbir yerde dönmediği için alan boş kalır; şıkkın kendisi satırdan gelir.
    expect(container.querySelector("#conn-password").value).toBe("");
    expect(container.querySelector("#conn-auth").value).toBe("sql");
    expect(container.querySelector("#conn-encrypt").checked).toBe(true);
    expect(container.querySelector("#conn-trust").checked).toBe(false);
    expect(container.innerHTML).toContain("Bağlantı · wwi_real");
  });

  it("ortam değişkeninin kazandığı satır okunur: alanlar kapalı, cümle bantta", async () => {
    api.connectionsGet.mockResolvedValue(ROWS[1]);
    await mount();
    await click(container.querySelector('[data-conn-edit="erp"]'));
    expect(container.querySelector("#conn-readonly").textContent).toBe(ENV_SOURCE_MESSAGE);
    for (const id of ["conn-server", "conn-database", "conn-auth", "conn-username", "conn-password", "conn-encrypt", "conn-trust"]) {
      expect(container.querySelector(`#${id}`).disabled).toBe(true);
    }
    expect(container.querySelector("#conn-test").disabled).toBe(true);
    expect(container.querySelector("#conn-save").disabled).toBe(true);
  });

  it("okuma düşünce cümle gelir, form denemeye açılmaz", async () => {
    api.connectionsGet.mockRejectedValue({ status: 409, message: "Bu veri kümesi SQL Server'a bağlı değil." });
    await mount();
    await click(container.querySelector('[data-conn-edit="yeni"]'));
    expect(container.querySelector("#conn-error").textContent).toContain("SQL Server'a bağlı değil");
    expect(container.querySelector("#conn-test").disabled).toBe(true);
  });
});

describe("ConnectionsScreen — denemek ve kaydetmek", () => {
  it("test formun o anki değerlerini gönderir", async () => {
    await mount();
    await click(container.querySelector('[data-conn-edit="wwi_real"]'));
    await click(container.querySelector("#conn-test"));
    expect(api.connectionsTest).toHaveBeenCalledWith("wwi_real", {
      server: "10.0.0.5",
      database: "WWI",
      auth: "sql",
      username: "bilgin_ro",
      password: "",
      options: { encrypt: true, trust_server_certificate: false, port: 1433, driver: "" },
    });
  });

  it("şifreleme şıkkının işareti options'a düşer", async () => {
    await mount();
    await click(container.querySelector('[data-conn-edit="wwi_real"]'));
    await toggle(container.querySelector("#conn-encrypt"));
    await click(container.querySelector("#conn-test"));
    expect(api.connectionsTest.mock.calls[0][1].options.encrypt).toBe(false);
  });

  it("sonuç satır satır okunur: ✓/✗, okunamayan tablolar ve giriş betiği", async () => {
    await mount();
    await click(container.querySelector('[data-conn-edit="wwi_real"]'));
    await click(container.querySelector("#conn-test"));
    const html = container.innerHTML;
    expect(html).toContain('id="conn-result"');
    expect(html).toContain("✗");
    expect(html).toContain("✓");
    expect(html).toContain("salt okunur bir giriş kullanın.");
    expect(html).toContain("TBLSTHAR bu girişle okunabiliyor.");
    expect(html).toContain('id="conn-missing"');
    expect(html).toContain("TBLFATUIRS");
    expect(html).toContain('id="conn-login-script"');
    expect(html).toContain('href="/api/datasets/wwi_real/login-script.sql"');
  });

  it("eksik form sunucuya gitmez: cümle alanın altında durur", async () => {
    await mount();
    await click(container.querySelector('[data-conn-edit="wwi_real"]'));
    await fill(container.querySelector("#conn-server"), "");
    await click(container.querySelector("#conn-test"));
    expect(api.connectionsTest).not.toHaveBeenCalled();
    expect(container.innerHTML).toContain("Sunucu adı boş olamaz.");
  });

  it("saklı sırrı olan satırda boş parola 'koru'dur: kaydetmede eksik sayılmaz", async () => {
    const onRefresh = vi.fn();
    await mount({ onRefresh });
    await click(container.querySelector('[data-conn-edit="wwi_real"]'));
    await submit();
    expect(api.connectionsSave).toHaveBeenCalledWith("wwi_real", expect.objectContaining({ password: "" }));
    expect(container.querySelector("#conn-note").textContent).toContain("Bağlantı kaydedildi.");
    expect(onRefresh).toHaveBeenCalled();
  });

  it("ilke kez kaydedilirken parola istenir: saklı sır yoksa cümle alanın altında", async () => {
    api.connectionsGet.mockResolvedValue(ROWS[2]);
    await mount();
    await click(container.querySelector('[data-conn-edit="yeni"]'));
    await fill(container.querySelector("#conn-server"), "10.0.0.9");
    await fill(container.querySelector("#conn-database"), "YENI");
    await submit();
    expect(api.connectionsSave).not.toHaveBeenCalled();
    expect(container.innerHTML).toContain("Parola zorunlu: bu bağlantı için henüz parola saklanmadı.");
  });

  it("reddin cümlesi bantta durur, form kapanmaz", async () => {
    api.connectionsSave.mockRejectedValue({ status: 409, message: "Bu giriş salt okunur değil; bağlantı kaydedilmedi." });
    await mount();
    await click(container.querySelector('[data-conn-edit="wwi_real"]'));
    await submit();
    expect(container.querySelector("#conn-error").textContent).toContain("salt okunur değil");
    expect(container.querySelector("#conn-server").value).toBe("10.0.0.5");
  });

  it("parolayı saklayamayan sunucu formu kapatır: cümleyi tanıyan alan bir daha sır sormaz", async () => {
    api.connectionsSave.mockRejectedValue({ status: 409, message: DPAPI_MESSAGE });
    await mount();
    await click(container.querySelector('[data-conn-edit="wwi_real"]'));
    await submit();
    expect(container.querySelector("#conn-error").textContent).toContain("parola saklanamaz");
    expect(container.querySelector("#conn-password").disabled).toBe(true);
    expect(container.querySelector("#conn-save").disabled).toBe(true);
  });

  // Ölü bir sunucu isteği hiç yanıtlamayabilir: ekranın kendi bütçesi dolduğunda düğme geri
  // gelir, cümle de beklemenin yerine geçer (T466).
  it("yanıt vermeyen deneme bütçesi dolunca düğmeyi geri getirir ve cümlesini yazar", async () => {
    api.connectionsTest.mockReturnValue(new Promise(() => {}));
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      await mount();
      await click(container.querySelector('[data-conn-edit="wwi_real"]'));
      await click(container.querySelector("#conn-test"));
      expect(container.querySelector("#conn-test").textContent).toBe("Deneniyor…");
      expect(container.querySelector("#conn-save").disabled).toBe(true);

      await act(async () => {
        vi.advanceTimersByTime(19000);
      });
      await settle();
      expect(container.querySelector("#conn-test").textContent).toBe("Deneniyor…");
      expect(container.querySelector("#conn-error")).toBeNull();

      await act(async () => {
        vi.advanceTimersByTime(1000);
      });
      await settle();

      expect(container.querySelector("#conn-test").textContent).toBe("Bağlantıyı test et");
      expect(container.querySelector("#conn-test").disabled).toBe(false);
      expect(container.querySelector("#conn-save").disabled).toBe(false);
      expect(container.querySelector("#conn-error").textContent).toContain("Sunucu 20 saniyede yanıt vermedi");
    } finally {
      vi.useRealTimers();
    }
  });
});
