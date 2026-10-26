// İş rolü (R7-16): yöneticinin defterinden geçer, başlıktaki çip de onu söyler. Seçili hal ve
// sütunun yeri SSR ile okunur; eklemenin gövdesi, değişimin isteği ve kendi satırındaki kapama
// olay ister, o yüzden ekran jsdom'da da kuruluyor.
// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App.jsx";
import * as api from "../lib/api.js";
import { BUSINESS_ROLES } from "../lib/startCards.js";
import UsersScreen from "./UsersScreen.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../lib/api.js", async (importOriginal) => ({
  ...(await importOriginal()),
  usersCreate: vi.fn(),
  usersUpdate: vi.fn(),
}));

const noop = () => {};

// Reddin cümlesi sunucunundur (auth_api.OWN_BUSINESS_ROLE); ekran onu yalnız ipucu olarak taşır.
const OWN = "Kendi iş rolünüzü değiştiremezsiniz.";

function person(over) {
  return {
    id: 1,
    username: "admin",
    role: "admin",
    business_role: "yonetim",
    active: true,
    created_at: "2026-10-20T09:00:00+00:00",
    last_login_at: "2026-10-26T08:15:00+00:00",
    ...over,
  };
}

const USERS = [person(), person({ id: 2, username: "analist", role: "user", business_role: "satis" })];

// /api/auth/me'nin sözleşmesi {username, role, business_role}: id yok, ekran kendi satırını addan çözüyor.
const ME = { username: "admin", role: "admin", business_role: "yonetim" };

let container;
let root;

function render(node) {
  return renderToStaticMarkup(node)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&");
}

const businessField = (id) => container.querySelector(`[data-user-business-role="${id}"]`);
const optionTexts = (select) => Array.from(select.options, (option) => option.textContent);

async function settle() {
  await act(async () => {
    for (let turn = 0; turn < 10; turn += 1) await Promise.resolve();
  });
}

async function mount(props = {}) {
  await act(async () => root.render(<UsersScreen users={USERS} onRefresh={noop} {...props} />));
  await settle();
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

async function changeBusiness(id, value) {
  await act(async () => {
    const select = businessField(id);
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await settle();
}

async function submit() {
  await act(async () => {
    const event = new Event("submit", { bubbles: true, cancelable: true });
    container.querySelector("#user-add-form").dispatchEvent(event);
  });
  await settle();
}

beforeEach(() => {
  vi.clearAllMocks();
  api.usersCreate.mockResolvedValue({});
  api.usersUpdate.mockResolvedValue({});
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("UsersScreen — iş rolü sütunu", () => {
  it("İş rolü sütunu Rol'ün ardından gelir; boş satır altı sütunu birden kapsar", () => {
    const html = render(<UsersScreen users={USERS} onRefresh={noop} />);
    expect(html).toContain(">İş rolü</th>");
    expect(html.indexOf('scope="col">Rol<')).toBeLessThan(html.indexOf('scope="col">İş rolü<'));
    expect(render(<UsersScreen users={[]} onRefresh={noop} />)).toContain('colSpan="6"');
  });

  it("her satır kendi iş rolünü seçili getirir", async () => {
    await mount();
    expect(businessField(1).value).toBe("yonetim");
    expect(businessField(2).value).toBe("satis");
    expect(optionTexts(businessField(2))).toEqual(BUSINESS_ROLES.map((item) => item.label));
  });

  it("iş rolü değişimi tek alanlık gövdeyle gönderilir ve cevabı not olur", async () => {
    await mount();
    await changeBusiness(2, "muhasebe");
    expect(api.usersUpdate).toHaveBeenCalledTimes(1);
    expect(api.usersUpdate).toHaveBeenCalledWith(2, { business_role: "muhasebe" });
    expect(container.textContent).toContain("“analist” iş rolü güncellendi.");
  });

  it("kendi satırında alan kapalı ve nedeni başlığında; öteki satırda açık", async () => {
    await mount({ currentUser: ME });
    const own = businessField(1);
    expect(own.disabled).toBe(true);
    expect(own.title).toBe(OWN);
    const other = businessField(2);
    expect(other.disabled).toBe(false);
    expect(other.hasAttribute("title")).toBe(false);
  });

  it("iş rolü olmayan satır varsayılanı, tanınmayan kod kendi adını taşır", async () => {
    await mount({
      users: [person({ id: 3, username: "kimsesiz", business_role: undefined }), person({ id: 4, username: "depo", business_role: "depo" })],
    });
    expect(businessField(3).value).toBe("genel");
    expect(businessField(4).value).toBe("depo");
    expect(optionTexts(businessField(4))).toContain("depo");
    expect(container.textContent).not.toMatch(/undefined|null/);
  });
});

describe("UsersScreen — yeni kullanıcıda iş rolü", () => {
  it("form beş rolü sırayla kurar ve Genel'i seçili getirir", async () => {
    await mount();
    const field = container.querySelector("#user-new-business-role");
    expect(optionTexts(field)).toEqual(BUSINESS_ROLES.map((item) => item.label));
    expect(field.value).toBe("genel");
  });

  it("ekleme iş rolünü business_role anahtarıyla gönderir", async () => {
    await mount();
    await fill(container.querySelector("#user-new-username"), "analist3");
    await fill(container.querySelector("#user-new-password"), "Parola-12345");
    await fill(container.querySelector("#user-new-password2"), "Parola-12345");
    await fill(container.querySelector("#user-new-business-role"), "muhasebe");
    await submit();
    expect(api.usersCreate).toHaveBeenCalledWith({
      username: "analist3",
      password: "Parola-12345",
      role: "user",
      business_role: "muhasebe",
    });
  });
});

describe("başlıkta iş rolü", () => {
  it("çip adı, iş rolünü ve rolü aynı sırayla söyler", () => {
    const html = render(<App user={{ username: "satis1", role: "user", business_role: "satis" }} />);
    expect(html).toContain('id="user-chip"');
    expect(html).toContain(">satis1 · Satış · Kullanıcı</span>");
  });

  it("yönetici çipi Yönetici der; iş rolü olmayan eski kimlik yalnız ad ve rolü taşır", () => {
    expect(render(<App user={{ username: "admin", role: "admin", business_role: "muhasebe" }} />)).toContain(
      ">admin · Muhasebe · Yönetici</span>",
    );
    const legacy = render(<App user={{ username: "admin", role: "admin" }} />);
    expect(legacy).toContain(">admin · Yönetici</span>");
    expect(legacy).not.toMatch(/undefined|· ·/);
  });

  it("tanınmayan iş rolü kendi koduyla okunur", () => {
    expect(render(<App user={{ username: "depo1", role: "user", business_role: "depo" }} />)).toContain(
      ">depo1 · depo · Kullanıcı</span>",
    );
  });
});
