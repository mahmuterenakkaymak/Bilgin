// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import App from "../App.jsx";
import { boot } from "../lib/auth.js";

const NOT_ALLOWED = "Bu sayfa yalnız yöneticiye açık.";
const ADMIN = { username: "admin", role: "admin" };
const USER = { username: "analist", role: "user" };

// App açılış adresini window.location.hash'ten okur; test ortamı node olduğu için pencere burada
// kurulur. SSR effect'leri çalıştırmadığı için dinleyici yuvaları boş durur.
function renderAt(hash, props = {}) {
  globalThis.window = {
    location: { hash },
    addEventListener: () => {},
    removeEventListener: () => {},
  };
  try {
    return renderToStaticMarkup(<App {...props} />);
  } finally {
    delete globalThis.window;
  }
}

describe("App rotayı rolle çözer", () => {
  it("sıradan kullanıcı #/kullanicilar ile açınca kullanıcı ekranı boyanmaz", () => {
    const html = renderAt("#/kullanicilar", { user: USER });
    expect(html).not.toContain('id="users-screen"');
    expect(html).not.toContain('id="user-add-form"');
    expect(html).toContain('id="main"');
    expect(html).toContain('id="route-note"');
    expect(html).toContain(NOT_ALLOWED);
  });

  it("yönetici #/kullanicilar ile açınca kullanıcı ekranı gelir, uyarı düşmez", () => {
    const html = renderAt("#/kullanicilar", { user: ADMIN });
    expect(html).toContain('id="users-screen"');
    expect(html).not.toContain('id="route-note"');
  });

  it("kullanıcısız kabuk tek kullanıcılıdır, ekranı gördüğü gibi açar", () => {
    expect(renderAt("#/kullanicilar")).toContain('id="users-screen"');
  });
});

describe("boot açılışta aynı kararı verir", () => {
  const api = (user) => ({ me: async () => user });

  it("sıradan kullanıcının açılış adresi soru ekranına düşer", async () => {
    expect(await boot(api(USER), "#/kullanicilar")).toEqual({
      screen: "app",
      user: USER,
      route: "ask",
      requested: "#/kullanicilar",
      note: NOT_ALLOWED,
    });
  });

  it("yönetici açtığı adreste kalır", async () => {
    expect(await boot(api(ADMIN), "#/kullanicilar")).toEqual({
      screen: "app",
      user: ADMIN,
      route: "users",
      requested: "#/kullanicilar",
      note: null,
    });
  });
});
