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

// Sözleşme "start card" ve "ready question"ın gerçekçi örnekleri: ekran bunları okur.
const card = { id: 3, title: "Eylül satışı", display: "number", value: 128500.5, refreshed_at: "2026-10-26T09:00:00Z" };
const ready = { id: 8, business_role: "satis", title: "Eylül satışı", display: "number", approved: false };

describe("başlangıç ekranı yolları", () => {
  it("kartlar GET olarak çekilir, gövde ve sorgu yoktur", async () => {
    const calls = stubFetch(jsonResponse(200, { cards: [card], business_role: "satis" }));
    await expect(api.start()).resolves.toEqual({ cards: [card], business_role: "satis" });
    expect(calls[0].path).toBe("/api/start");
    expect(calls[0].init.method).toBe("GET");
    expect(calls[0].init.body).toBeUndefined();
  });

  it("yenile ve aç POST olarak gider", async () => {
    const calls = stubFetch(jsonResponse(200, { card }));
    await api.startRefresh(3);
    await api.startOpen(3);
    expect(calls.map((call) => [call.path, call.init.method])).toEqual([
      ["/api/start/cards/3/refresh", "POST"],
      ["/api/start/cards/3/open", "POST"],
    ]);
    expect(calls[0].init.body).toBeUndefined();
  });

  it("kişisel kart bir soru kaydından eklenir: gövdede sql yoktur", async () => {
    const calls = stubFetch(jsonResponse(200, { card }));
    await api.pinCard({ audit_id: "a-1", title: "Eylül satışı", display: "number" });
    expect(calls[0].path).toBe("/api/start/cards");
    expect(calls[0].init.method).toBe("POST");
    expect(JSON.parse(calls[0].init.body)).toEqual({ audit_id: "a-1", title: "Eylül satışı", display: "number" });
  });

  it("başlık ve görünüm söylenmezse boş hâlleriyle gider", async () => {
    const calls = stubFetch(jsonResponse(200, { card }));
    await api.pinCard({ audit_id: "a-1" });
    expect(JSON.parse(calls[0].init.body)).toEqual({ audit_id: "a-1", title: "", display: null });
  });

  it("kişisel kart DELETE ile silinir", async () => {
    const calls = stubFetch(jsonResponse(200, { deleted: 3 }));
    await expect(api.unpinCard(3)).resolves.toEqual({ deleted: 3 });
    expect(calls[0].path).toBe("/api/start/cards/3");
    expect(calls[0].init.method).toBe("DELETE");
  });

  it("yenileme sınırının ve kotanın cümlesi ApiError olarak okunur", async () => {
    stubFetch(jsonResponse(429, { detail: "Bu kart az önce yenilendi; 12 sn sonra yeniden deneyin." }));
    const soon = await api.startRefresh(3).catch((error) => error);
    expect([soon.status, soon.message]).toEqual([429, "Bu kart az önce yenilendi; 12 sn sonra yeniden deneyin."]);

    stubFetch(jsonResponse(409, { detail: "En fazla 6 kişisel kart ekleyebilirsiniz." }));
    const full = await api.pinCard({ audit_id: "a-1" }).catch((error) => error);
    expect([full.status, full.message]).toEqual([409, "En fazla 6 kişisel kart ekleyebilirsiniz."]);
  });
});

describe("hazır soru yolları", () => {
  it("liste sorgusuz çekilir", async () => {
    const calls = stubFetch(jsonResponse(200, { ready_questions: [ready] }));
    await expect(api.readyList()).resolves.toEqual({ ready_questions: [ready] });
    expect(calls[0].path).toBe("/api/ready-questions");
    expect(calls[0].init.method).toBe("GET");
  });

  it("küme ve bekleme süzgeci adrese yazılır; false da yazılır", async () => {
    const calls = stubFetch(jsonResponse(200, { ready_questions: [] }));
    await api.readyList({ dataset: "wwi", pending: true });
    await api.readyList({ pending: false });
    await api.readyList({ dataset: "wwi" });
    expect(calls.map((call) => call.path)).toEqual([
      "/api/ready-questions?dataset=wwi&pending=true",
      "/api/ready-questions?pending=false",
      "/api/ready-questions?dataset=wwi",
    ]);
  });

  it("küme adı adres içinde kodlanır", async () => {
    const calls = stubFetch(jsonResponse(200, { ready_questions: [] }));
    await api.readyList({ dataset: "özel küme" });
    const query = new URLSearchParams(calls[0].path.split("?")[1]);
    expect(query.get("dataset")).toBe("özel küme");
  });

  it("onay gövdesi sözleşme alanlarıyla POST edilir, sql gitmez", async () => {
    const calls = stubFetch(jsonResponse(200, { ready_question: ready }));
    const body = { audit_id: "a-1", title: "Eylül satışı", question: "Eylül satışı ne kadar?", display: "number", business_role: "satis", position: 2 };
    await expect(api.readyCreate(body)).resolves.toEqual({ ready_question: ready });
    expect(calls[0].path).toBe("/api/ready-questions");
    expect(calls[0].init.method).toBe("POST");
    expect(JSON.parse(calls[0].init.body)).toEqual(body);
  });

  it("güncelleme PUT, silme DELETE; kimlik kodlanır", async () => {
    const calls = stubFetch(jsonResponse(200, { ready_question: ready }));
    await api.readyUpdate(8, { title: "Net satış", audit_id: "a-2" });
    await api.readyRemove(8);
    expect(calls.map((call) => [call.path, call.init.method])).toEqual([
      ["/api/ready-questions/8", "PUT"],
      ["/api/ready-questions/8", "DELETE"],
    ]);
    expect(JSON.parse(calls[0].init.body)).toEqual({ title: "Net satış", audit_id: "a-2" });
  });

  it("yönetici olmayan birinin erişimi 403 olarak okunur", async () => {
    stubFetch(jsonResponse(403, { detail: "Bu işlem yönetici içindir." }));
    const error = await api.readyRemove(8).catch((err) => err);
    expect(error).toBeInstanceOf(api.ApiError);
    expect([error.status, error.message]).toEqual([403, "Bu işlem yönetici içindir."]);
  });
});

describe("öneri işi yolları", () => {
  it("iş kümeyle ya da boş dizeyle başlatılır", async () => {
    const calls = stubFetch(jsonResponse(200, { job_id: "j-1" }));
    await expect(api.readySuggest("wwi")).resolves.toEqual({ job_id: "j-1" });
    await api.readySuggest();
    expect(calls[0].path).toBe("/api/ready-questions/suggest");
    expect(calls[0].init.method).toBe("POST");
    expect(JSON.parse(calls[0].init.body)).toEqual({ dataset: "wwi" });
    expect(JSON.parse(calls[1].init.body)).toEqual({ dataset: "" });
  });

  it("aşama GET ile yoklanır, iş kimliği kodlanır", async () => {
    const calls = stubFetch(jsonResponse(200, { job_id: "j/1", dataset: "wwi", phase: "asking", asked: 3, stored: 2, message: null }));
    await api.readySuggestStatus("j/1");
    expect(calls[0].path).toBe("/api/ready-questions/suggest/j%2F1");
    expect(calls[0].init.method).toBe("GET");
  });

  it("olmayan işin cümlesi ApiError olarak okunur", async () => {
    stubFetch(jsonResponse(404, { detail: "Öneri işi bulunamadı." }));
    const error = await api.readySuggestStatus("j-yok").catch((err) => err);
    expect([error.status, error.message]).toEqual([404, "Öneri işi bulunamadı."]);
  });
});
