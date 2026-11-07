// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "./api.js";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => (body === undefined ? "" : typeof body === "string" ? body : JSON.stringify(body)),
  };
}

function stubFetch(result) {
  const calls = [];
  globalThis.fetch = vi.fn(async (path, init) => {
    calls.push({ path, init });
    return result;
  });
  return calls;
}

describe("konuşma yolları", () => {
  it("liste GET olarak çekilir ve gövdesi yoktur", async () => {
    const calls = stubFetch(jsonResponse(200, { conversations: [{ id: "kon1", title: "Eylül satışı", turns: 2 }] }));
    await expect(api.conversationsList()).resolves.toEqual({ conversations: [{ id: "kon1", title: "Eylül satışı", turns: 2 }] });
    expect(calls[0].path).toBe("/api/conversations");
    expect(calls[0].init.method).toBe("GET");
    expect(calls[0].init.body).toBeUndefined();
  });

  it("tek konuşma kimlikle açılır, turlarıyla döner", async () => {
    const calls = stubFetch(jsonResponse(200, { conversation: { id: "kon1" }, turns: [{ n: 1 }] }));
    await expect(api.conversationGet("kon1")).resolves.toEqual({ conversation: { id: "kon1" }, turns: [{ n: 1 }] });
    expect(calls[0].path).toBe("/api/conversations/kon1");
    expect(calls[0].init.method).toBe("GET");
  });

  it("konuşma silinir ve DELETE olarak gider", async () => {
    const calls = stubFetch(jsonResponse(200, { deleted: true }));
    await expect(api.conversationDelete("kon1")).resolves.toEqual({ deleted: true });
    expect(calls[0].path).toBe("/api/conversations/kon1");
    expect(calls[0].init.method).toBe("DELETE");
  });

  it("kimlik adres içinde kodlanır", async () => {
    const calls = stubFetch(jsonResponse(200, { conversation: { id: "a/b" }, turns: [] }));
    await api.conversationGet("a/b");
    await api.conversationDelete("a/b");
    expect(calls.map((call) => call.path)).toEqual(["/api/conversations/a%2Fb", "/api/conversations/a%2Fb"]);
  });

  it("olmayan konuşmanın cümlesi ApiError olarak okunur", async () => {
    stubFetch(jsonResponse(404, { detail: "Konuşma bulunamadı." }));
    const error = await api.conversationGet("yok").catch((err) => err);
    expect(error).toBeInstanceOf(api.ApiError);
    expect({ status: error.status, message: error.message }).toEqual({ status: 404, message: "Konuşma bulunamadı." });
  });
});

describe("ask konuşma kimliği taşır", () => {
  it("kimlik verildiğinde gövdeye girer", async () => {
    const calls = stubFetch(jsonResponse(200, { status: "answered", conversation_id: "kon1", turn: 2 }));
    await api.ask({ question: "Ya Ağustos?", mode: "rag", choice: "Net satış", conversation_id: "kon1" });
    expect(JSON.parse(calls[0].init.body)).toEqual({
      question: "Ya Ağustos?",
      mode: "rag",
      choice: "Net satış",
      conversation_id: "kon1",
    });
  });

  it("kimlik yoksa anahtar gövdeye hiç girmez", async () => {
    const calls = stubFetch(jsonResponse(200, { status: "answered" }));
    await api.ask({ question: "Kimler?" });
    expect(Object.keys(JSON.parse(calls[0].init.body))).toEqual(["question", "mode", "choice"]);
  });
});
