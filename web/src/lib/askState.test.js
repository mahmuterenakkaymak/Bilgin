import { describe, expect, it } from "vitest";
import failedLlm from "../fixtures/failed_llm.json";
import { askReducer, initialState } from "./askState.js";

const ANSWERED = { status: "answered", question: "Ankara'daki alıcılar kimler?", choice: null, row_count: 3 };
const CLARIFY = { status: "needs_clarification", question: "Eylül 2026'da satışlarımız ne kadar?", choice: null };

function run(...actions) {
  return actions.reduce((state, action) => askReducer(state, action), initialState);
}

describe("askState indirgeyicisi", () => {
  it("açılışta boş: ne soru ne yük ne hata", () => {
    expect(initialState).toEqual({ status: "idle", question: "", choice: null, payload: null, error: null });
  });

  it("ask yüklemeye alır, soruyu ve seçimi taşır", () => {
    expect(askReducer(initialState, { type: "ask", question: "Kimler?" })).toEqual({
      status: "loading",
      question: "Kimler?",
      choice: null,
      payload: null,
      error: null,
    });
  });

  it("ask önceki cevabı ve hatayı temizler", () => {
    const answered = askReducer(askReducer(initialState, { type: "ask", question: "Kimler?" }), {
      type: "receive",
      payload: ANSWERED,
    });
    const next = askReducer(answered, { type: "ask", question: "Kaç fatura?" });
    expect({ status: next.status, question: next.question, payload: next.payload, error: next.error }).toEqual({
      status: "loading",
      question: "Kaç fatura?",
      payload: null,
      error: null,
    });
  });

  it("cevaplanan payload answered olur", () => {
    const state = run({ type: "ask", question: "Ankara'daki alıcılar kimler?" }, { type: "receive", payload: ANSWERED });
    expect(state.status).toBe("answered");
    expect(state.payload).toBe(ANSWERED);
    expect(state.error).toBeNull();
  });

  it("netleştirme payloadı clarifying olur", () => {
    expect(run({ type: "ask", question: "Satış ne kadar?" }, { type: "receive", payload: CLARIFY }).status).toBe(
      "clarifying",
    );
  });

  it("başarısız payload hatanın adını ve cümlesini taşır", () => {
    const state = run({ type: "ask", question: failedLlm.question }, { type: "receive", payload: failedLlm });
    expect(state.status).toBe("failed");
    expect(state.error).toEqual({ kind: failedLlm.error.kind, message: failedLlm.error.message });
    expect(state.question).toBe(failedLlm.question);
  });

  it("hata taşımayan başarısız payload genel cümleyle karşılanır", () => {
    const state = askReducer(initialState, { type: "receive", payload: { status: "failed", question: "Kimler?" } });
    expect(state.status).toBe("failed");
    expect(state.error).toEqual({ kind: "failed", message: "Cevap üretilemedi." });
  });

  it("eksik payload ağdan gelen bozuk yanıttır, çökmez", () => {
    const state = askReducer(askReducer(initialState, { type: "ask", question: "Kimler?" }), { type: "receive" });
    expect(state.status).toBe("failed");
    expect(state.payload).toBeNull();
  });

  it("fail ağı network_error, diğerini failed yapar", () => {
    expect(askReducer(initialState, { type: "fail", kind: "network", message: "Sunucuya ulaşılamadı" })).toMatchObject({
      status: "network_error",
      error: { kind: "network", message: "Sunucuya ulaşılamadı" },
    });
    expect(askReducer(initialState, { type: "fail", kind: "failed", message: "Sunucu hatası (500)." })).toMatchObject({
      status: "failed",
      error: { kind: "failed", message: "Sunucu hatası (500)." },
    });
  });

  it("reset boş ekrana döndürür ve başlangıç durumu bozulmaz", () => {
    const used = run({ type: "ask", question: "Kimler?" }, { type: "receive", payload: ANSWERED });
    expect(askReducer(used, { type: "reset" })).toEqual(initialState);
    expect(initialState.status).toBe("idle");
    expect(initialState.payload).toBeNull();
  });

  it("tanınmayan eylem durumu olduğu gibi bırakır", () => {
    const loading = askReducer(initialState, { type: "ask", question: "Kimler?" });
    expect(askReducer(loading, { type: "bilinmeyen" })).toBe(loading);
    expect(askReducer(undefined, {})).toBe(initialState);
  });
});
