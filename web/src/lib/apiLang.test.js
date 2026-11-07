// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "./api.js";

const originalFetch = globalThis.fetch;

// Dil modül düzeyinde bir durum: sıradaki test öncekinin dilini görmesin.
afterEach(() => {
  globalThis.fetch = originalFetch;
  api.setApiLang(null);
});

function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => (body === undefined ? "" : JSON.stringify(body)),
  };
}

function blobResponse() {
  return { ok: true, status: 200, blob: async () => "XLSX" };
}

function stubFetch(result = jsonResponse(200, { status: "ok" })) {
  const calls = [];
  globalThis.fetch = vi.fn(async (path, init) => {
    calls.push({ path, init });
    return result;
  });
  return calls;
}

describe("api'nin arayüz dili", () => {
  it("dil henüz çözülmediyse hiçbir istek Accept-Language taşımaz", async () => {
    const calls = stubFetch();
    await api.health();
    await api.ask({ question: "Merhaba" });
    expect(calls[0].init.headers).toBeUndefined();
    expect(calls[1].init.headers).toEqual({ "Content-Type": "application/json" });
  });

  it("setApiLang sonrası her yöntem başlığı taşır", async () => {
    api.setApiLang("en");
    const calls = stubFetch();
    await api.health();
    await api.ask({ question: "Satış ne kadar?" });
    await api.setMyLang("en");
    await api.conversationDelete("a1b2");
    expect(calls.map((call) => [call.path, call.init.method])).toEqual([
      ["/api/health", "GET"],
      ["/api/ask", "POST"],
      ["/api/auth/me", "PUT"],
      ["/api/conversations/a1b2", "DELETE"],
    ]);
    for (const call of calls) expect(call.init.headers["Accept-Language"]).toBe("en");
    expect(calls[0].init.headers).toEqual({ "Accept-Language": "en" });
    expect(calls[1].init.headers).toEqual({ "Content-Type": "application/json", "Accept-Language": "en" });
  });

  it("başlık dil değiştikçe yenisiyle gider, seçimden çıkınca kalkar", async () => {
    api.setApiLang("en");
    let calls = stubFetch();
    await api.health();
    expect(calls[0].init.headers).toEqual({ "Accept-Language": "en" });

    api.setApiLang("tr");
    calls = stubFetch();
    await api.health();
    expect(calls[0].init.headers).toEqual({ "Accept-Language": "tr" });

    api.setApiLang(null);
    calls = stubFetch();
    await api.health();
    expect(calls[0].init.headers).toBeUndefined();
  });

  it("setMyLang dili PUT /api/auth/me gövdesine yazar ve güncellenmiş kişiyi döndürür", async () => {
    const calls = stubFetch(jsonResponse(200, { username: "admin", role: "admin", lang: "en" }));
    await expect(api.setMyLang("en")).resolves.toEqual({ username: "admin", role: "admin", lang: "en" });
    expect(calls[0].path).toBe("/api/auth/me");
    expect(calls[0].init.method).toBe("PUT");
    expect(JSON.parse(calls[0].init.body)).toEqual({ lang: "en" });
  });

  it("şablon adresı dili sorgu parametresi olarak taşır", () => {
    expect(api.mapTemplateUrl(false)).toBe("/api/schema-map/template.xlsx");
    api.setApiLang("en");
    expect(api.mapTemplateUrl(false)).toBe("/api/schema-map/template.xlsx?lang=en");
    expect(api.mapTemplateUrl(true)).toBe("/api/schema-map/template.xlsx?from_db=1&lang=en");
    api.setApiLang("tr");
    expect(api.mapTemplateUrl(true)).toBe("/api/schema-map/template.xlsx?from_db=1&lang=tr");
  });

  it("şablonu indiren fetch de dili başlıkla taşır", async () => {
    api.setApiLang("en");
    const calls = stubFetch(blobResponse());
    await expect(api.mapTemplateDownload(false)).resolves.toEqual({ blob: "XLSX", note: null });
    expect(calls[0].path).toBe("/api/schema-map/template.xlsx?lang=en");
    expect(calls[0].init.headers).toEqual({ "Accept-Language": "en" });
  });
});
