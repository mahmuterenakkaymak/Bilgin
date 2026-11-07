// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "./api.js";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
  api.onUnauthorized(() => {});
});

function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => (body === undefined ? "" : JSON.stringify(body)),
  };
}

function stubFetch(result) {
  const calls = [];
  globalThis.fetch = vi.fn(async (path, init) => {
    calls.push({ path, init });
    return typeof result === "function" ? result(path) : result;
  });
  return calls;
}

describe("auth yolları", () => {
  it("me GET olarak oturum kullanıcısını okur", async () => {
    const calls = stubFetch(jsonResponse(200, { username: "admin", role: "admin" }));
    await expect(api.me()).resolves.toEqual({ username: "admin", role: "admin" });
    expect(calls[0].path).toBe("/api/auth/me");
    expect(calls[0].init.method).toBe("GET");
    expect(calls[0].init.body).toBeUndefined();
  });

  it("login kullanıcı adı ve parolayı gövdede gönderir, kullanıcıyı döndürür", async () => {
    const calls = stubFetch(jsonResponse(200, { username: "admin", role: "admin" }));
    await expect(api.login({ username: "admin", password: "gizli-parola" })).resolves.toEqual({
      username: "admin",
      role: "admin",
    });
    expect(calls[0].path).toBe("/api/auth/login");
    expect(calls[0].init.method).toBe("POST");
    expect(calls[0].init.headers).toEqual({ "Content-Type": "application/json" });
    expect(JSON.parse(calls[0].init.body)).toEqual({ username: "admin", password: "gizli-parola" });
  });

  it("logout POST olarak çıkar", async () => {
    const calls = stubFetch(jsonResponse(200, { ok: true }));
    await api.logout();
    expect(calls[0].path).toBe("/api/auth/logout");
    expect(calls[0].init.method).toBe("POST");
    expect(calls[0].init.body).toBeUndefined();
  });
});

describe("onUnauthorized", () => {
  it("401 handler'ı ApiError fırlatılmadan önce çalıştırır", async () => {
    const order = [];
    stubFetch(jsonResponse(401, { detail: "Oturum açmanız gerekiyor." }));
    api.onUnauthorized(() => order.push("handler"));
    await api.history().catch((error) => order.push(`hata:${error.status}`));
    expect(order).toEqual(["handler", "hata:401"]);
  });

  it("girişin 401'i handler'a değil forma gider", async () => {
    const handler = vi.fn();
    stubFetch(jsonResponse(401, { detail: "Kullanıcı adı veya parola hatalı." }));
    api.onUnauthorized(handler);
    const error = await api
      .login({ username: "admin", password: "yanlis" })
      .catch((err) => err);
    expect(handler).not.toHaveBeenCalled();
    expect({ status: error.status, message: error.message }).toEqual({
      status: 401,
      message: "Kullanıcı adı veya parola hatalı.",
    });
  });

  it("sağlık isteğinin 401'i de handler'a düşer", async () => {
    const handler = vi.fn();
    stubFetch(jsonResponse(401, { detail: "Oturum açmanız gerekiyor." }));
    api.onUnauthorized(handler);
    await api.health().catch(() => {});
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("401 dışında handler çalışmaz", async () => {
    const handler = vi.fn();
    stubFetch((path) => (path === "/api/rules" ? jsonResponse(500, { detail: "bozuk" }) : jsonResponse(200, {})));
    api.onUnauthorized(handler);
    await api.history();
    await api.rulesList().catch(() => {});
    expect(handler).not.toHaveBeenCalled();
  });
});
