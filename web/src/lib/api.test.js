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
    if (result instanceof Error) throw result;
    return result;
  });
  return calls;
}

describe("api çağrıları", () => {
  it("okuma yolları GET olarak çekilir ve gövdesi yoktur", async () => {
    const calls = stubFetch(jsonResponse(200, { status: "ok" }));
    await api.health();
    await api.examples();
    await api.tables();
    await api.history();
    await api.savedList();
    await api.rulesList();
    expect(calls.map((call) => call.path)).toEqual([
      "/api/health",
      "/api/examples",
      "/api/tables",
      "/api/history",
      "/api/saved",
      "/api/rules",
    ]);
    expect(calls[0].init.method).toBe("GET");
    expect(calls[0].init.body).toBeUndefined();
    expect(calls[0].init.headers).toBeUndefined();
  });

  it("ask soruyu mod ve seçimle birlikte gönderir", async () => {
    const calls = stubFetch(jsonResponse(200, { status: "answered" }));
    await expect(api.ask({ question: "Eylül satışı ne kadar?" })).resolves.toEqual({ status: "answered" });
    expect(calls[0].path).toBe("/api/ask");
    expect(calls[0].init.method).toBe("POST");
    expect(calls[0].init.headers).toEqual({ "Content-Type": "application/json" });
    expect(JSON.parse(calls[0].init.body)).toEqual({ question: "Eylül satışı ne kadar?", mode: null, choice: null });
  });

  it("netleşme seçeneği seçim olarak, mod mod olarak gider", async () => {
    const calls = stubFetch(jsonResponse(200, {}));
    await api.ask({ question: "Satış ne kadar?", mode: "rag", choice: "KDV dahil" });
    expect(JSON.parse(calls[0].init.body)).toEqual({ question: "Satış ne kadar?", mode: "rag", choice: "KDV dahil" });
  });

  it("kayıt ekler, siler; soru metni ve SQL gider", async () => {
    const calls = stubFetch(jsonResponse(200, { saved: { id: 3 } }));
    await api.savedAdd({ question: "Kimler?", sql: "SELECT 1" });
    await api.savedRemove(3);
    expect(calls[0].path).toBe("/api/saved");
    expect(calls[0].init.method).toBe("POST");
    expect(JSON.parse(calls[0].init.body)).toEqual({ question: "Kimler?", mode: null, sql: "SELECT 1" });
    expect(calls[1].path).toBe("/api/saved/3");
    expect(calls[1].init.method).toBe("DELETE");
  });

  it("kural ekler, günceller, siler ve indeksi yeniden kurar", async () => {
    const calls = stubFetch(jsonResponse(200, { rules: [] }));
    await api.rulesCreate({ id: "satis", term: "Satış" });
    await api.rulesUpdate("satis", { id: "satis", term: "Net satış" });
    await api.rulesRemove("satis");
    await api.rebuild();
    expect(calls.map((call) => [call.path, call.init.method])).toEqual([
      ["/api/rules", "POST"],
      ["/api/rules/satis", "PUT"],
      ["/api/rules/satis", "DELETE"],
      ["/api/index/rebuild", "POST"],
    ]);
    expect(JSON.parse(calls[1].init.body)).toEqual({ id: "satis", term: "Net satış" });
  });

  it("dışa aktarım adresı kimlikle ve uzantıyla kurulur", () => {
    expect(api.exportUrl("a1b2c3", "csv")).toBe("/api/export/a1b2c3.csv");
    expect(api.exportUrl("a1b2c3", "xlsx")).toBe("/api/export/a1b2c3.xlsx");
    expect(api.exportUrl("a/b")).toBe("/api/export/a%2Fb.csv");
  });
});

describe("api hataları", () => {
  it("detail cümlesi message olur, errors boş kalır", async () => {
    stubFetch(jsonResponse(400, { detail: "Soru boş." }));
    const error = await api.ask({ question: "  " }).catch((err) => err);
    expect(error).toBeInstanceOf(api.ApiError);
    expect(error).toBeInstanceOf(Error);
    expect({ status: error.status, message: error.message, errors: error.errors }).toEqual({
      status: 400,
      message: "Soru boş.",
      errors: [],
    });
  });

  it("422 alan hataları hem message hem errors olarak okunur", async () => {
    stubFetch(jsonResponse(422, { errors: [{ field: "term", message: "Terim boş." }, { field: "id", message: "Kimlik zorunlu." }] }));
    const error = await api.rulesCreate({}).catch((err) => err);
    expect(error.status).toBe(422);
    expect(error.message).toBe("Terim boş.");
    expect(error.errors).toEqual([
      { field: "term", message: "Terim boş." },
      { field: "id", message: "Kimlik zorunlu." },
    ]);
  });

  it("detail alan listesi taşıyorsa errors oradan gelir", async () => {
    stubFetch(jsonResponse(409, { detail: [{ field: "id", message: "Bu kimlikte bir kural zaten var: satis." }] }));
    const error = await api.rulesCreate({ id: "satis" }).catch((err) => err);
    expect(error.status).toBe(409);
    expect(error.message).toBe("Bu kimlikte bir kural zaten var: satis.");
    expect(error.errors).toEqual([{ field: "id", message: "Bu kimlikte bir kural zaten var: satis." }]);
  });

  it("FastAPI kendi 422 hatası loc ve msg alanlarından okunur", async () => {
    stubFetch(jsonResponse(422, { detail: [{ loc: ["body", "question"], msg: "Input should be a valid string" }] }));
    const error = await api.ask({ question: 1 }).catch((err) => err);
    expect(error.errors).toEqual([{ field: "question", message: "Input should be a valid string" }]);
  });

  it("JSON olmayan gövde genel bir cümleyle karşılanır", async () => {
    stubFetch(jsonResponse(502, "<html>Bad Gateway</html>"));
    const error = await api.health().catch((err) => err);
    expect(error.status).toBe(502);
    expect(error.message).toBe("Sunucu hatası (502).");
    expect(error.errors).toEqual([]);
  });

  it("ağ hatası status 0 ile döner", async () => {
    stubFetch(new TypeError("Failed to fetch"));
    const error = await api.health().catch((err) => err);
    expect(error).toBeInstanceOf(api.ApiError);
    expect({ status: error.status, message: error.message }).toEqual({ status: 0, message: "Sunucuya ulaşılamadı" });
  });

  it("gövde okunurken kopan bağlantı da ağ hatasıdır", async () => {
    globalThis.fetch = vi.fn(async () => ({ ok: true, status: 200, text: async () => { throw new TypeError("cop"); } }));
    const error = await api.history().catch((err) => err);
    expect(error.status).toBe(0);
  });
});
