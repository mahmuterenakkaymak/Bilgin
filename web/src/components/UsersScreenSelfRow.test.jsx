// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// Kendi satırının korunumu (M21 review 4): hangi satırın oturum sahibi olduğu, düğmenin
// kalkması ve rolün onaydan geçmesi olay + etki ister — SSR ikisini de çalıştırmaz.
// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../lib/api.js";
import UsersScreen from "./UsersScreen.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../lib/api.js", async (importOriginal) => ({
  ...(await importOriginal()),
  usersUpdate: vi.fn(),
}));

const noop = () => {};

const USERS = [
  {
    id: 1,
    username: "admin",
    role: "admin",
    active: true,
    created_at: "2026-10-20T09:00:00+00:00",
    last_login_at: "2026-10-26T08:15:00+00:00",
  },
  {
    id: 2,
    username: "analist",
    role: "user",
    active: true,
    created_at: "2026-10-21T09:00:00+00:00",
    last_login_at: null,
  },
];

// /api/auth/me'nin sözleşmesi {username, role}: id yok, ekran kendi satırını addan çözüyor.
const ME = { username: "admin", role: "admin" };

let container;
let root;
let confirm;

const settle = async () => {
  await act(async () => {
    for (let turn = 0; turn < 10; turn += 1) await Promise.resolve();
  });
};

async function mount(props = {}) {
  await act(async () => root.render(<UsersScreen users={USERS} onRefresh={noop} {...props} />));
  await settle();
}

// Rol seçimi satırın kendi select'inden geçer: id'si kullanıcınınki, değeri yeni rol.
async function changeRole(id, role) {
  const select = container.querySelector(`[data-user-role="${id}"]`);
  await act(async () => {
    select.value = role;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await settle();
}

beforeEach(() => {
  vi.clearAllMocks();
  api.usersUpdate.mockResolvedValue({});
  confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

describe("UsersScreen — oturum sahibinin kendi satırı", () => {
  it("kendi satırında pasifleştirme düğmesi kurulmaz; diğer satırda durur", async () => {
    await mount({ currentUser: ME });
    expect(container.querySelector('[data-user-toggle="1"]')).toBeNull();
    expect(container.querySelectorAll("[data-user-toggle]")).toHaveLength(1);
    expect(container.querySelector('[data-user-toggle="2"]')?.textContent).toBe("Pasifleştir");
  });

  it("kimlik yoksa (oturum kapısı yok) her satır kendi düğmesini taşır", async () => {
    await mount();
    expect(container.querySelector('[data-user-toggle="1"]')?.textContent).toBe("Pasifleştir");
    expect(container.querySelector('[data-user-toggle="2"]')?.textContent).toBe("Pasifleştir");
  });

  it("kendi rolü reddedilen onaydan sonra istek göndermez ve seçimi eski halinde kalır", async () => {
    await mount({ currentUser: ME });
    await changeRole(1, "user");
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(api.usersUpdate).not.toHaveBeenCalled();
    expect(container.querySelector('[data-user-role="1"]').value).toBe("admin");
  });

  it("kendi rolü yalnız onay verilince güncellenir", async () => {
    await mount({ currentUser: ME });
    confirm.mockReturnValue(true);
    await changeRole(1, "user");
    expect(api.usersUpdate).toHaveBeenCalledTimes(1);
    expect(api.usersUpdate).toHaveBeenCalledWith(1, { role: "user" });
  });

  it("başkasının satırı sormaz, doğrudan güncellenir", async () => {
    await mount({ currentUser: ME });
    await changeRole(2, "admin");
    expect(confirm).not.toHaveBeenCalled();
    expect(api.usersUpdate).toHaveBeenCalledTimes(1);
    expect(api.usersUpdate).toHaveBeenCalledWith(2, { role: "admin" });
  });
});
