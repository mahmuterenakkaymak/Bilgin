import { describe, expect, it } from "vitest";
import { initialState, threadReducer } from "./thread.js";

// Depodan gelen konuşma: 1. tur cevaplı, 2. tur şık bekliyor (Contracts "StoredTurn").
const STORED = [
  {
    n: 1,
    question: "Eylül satışı ne kadar?",
    choice: null,
    status: "answered",
    sql: "SELECT SUM(HTUR_MIKTARI) FROM ...",
    answer_text: "Eylül satışı 8.910 adet.",
    audit_id: "aa1",
    created_at: "2026-10-20T09:00:00+00:00",
    summary: {
      columns: ["SATIS"],
      row_count: 1,
      rows: [[8910]],
      facts: [{ name: "total", display: "8.910" }],
      chart_kind: "bar",
      context: null,
      clarification: null,
    },
  },
  {
    n: 2,
    question: "Bu müşteri kaç sipariş verdi?",
    choice: null,
    status: "needs_clarification",
    sql: null,
    answer_text: "",
    audit_id: "aa2",
    created_at: "2026-10-20T09:01:00+00:00",
    summary: {
      columns: [],
      row_count: 0,
      rows: [],
      facts: [],
      chart_kind: null,
      context: null,
      clarification: { question: "Hangi müşteriyi kastediyorsunuz?", options: ["C1 (A)", "C2 (B)"] },
    },
  },
];

const ANSWERED = {
  status: "answered",
  question: "Bu müşteri kaç sipariş verdi?",
  choice: "C1 (A)",
  answer_text: "C1 müşterisinin 12 siparişi var.",
  sql: "SELECT COUNT(*) FROM ...",
  audit_id: "aa3",
  conversation_id: "kon1",
  turn: 2,
  columns: ["SIPARIS_SAYISI"],
  rows: [[12]],
  row_count: 1,
  facts: [{ name: "row_count", display: "1" }],
  chart: { kind: "bar" },
  context: { uses_turns: [1], line: "Önceki cevaptan: müşteri C1 (A)" },
  clarification: null,
};

function loaded(...actions) {
  return actions.reduce((state, action) => threadReducer(state, action), threadReducer(initialState, { type: "load", conversation: { id: "kon1" }, turns: STORED }));
}

describe("thread indirgeyicisi", () => {
  it("açılışta boş: ne konuşma ne tur", () => {
    expect(initialState).toEqual({ conversationId: null, turns: [] });
    expect(threadReducer(undefined, {})).toBe(initialState);
  });

  it("kayıtlı turlar yüklenir: kimlik, sıralı turlar, son tur açık", () => {
    const state = threadReducer(initialState, { type: "load", conversation: { id: "kon1" }, turns: STORED });
    expect(state.conversationId).toBe("kon1");
    expect(state.turns).toHaveLength(2);
    expect(state.turns[0]).toMatchObject({
      n: 1,
      question: "Eylül satışı ne kadar?",
      choice: null,
      status: "answered",
      answer_text: "Eylül satışı 8.910 adet.",
      sql: "SELECT SUM(HTUR_MIKTARI) FROM ...",
      audit_id: "aa1",
      payload: null,
      stored: true,
      pending: false,
      expanded: false,
    });
    expect(state.turns[0].summary).toMatchObject({ row_count: 1, rows: [[8910]], chart_kind: "bar" });
    expect(state.turns[0].collapsed).toBe(true);
    expect(state.turns[1].collapsed).toBe(false);
    expect(state.turns[1].summary.clarification.options).toEqual(["C1 (A)", "C2 (B)"]);
  });

  it("konuşma ya da tur listesi yoksa boş akış, çökmez", () => {
    expect(threadReducer(initialState, { type: "load" })).toEqual({ conversationId: null, turns: [] });
    expect(threadReducer(initialState, { type: "load", conversation: null, turns: null }).turns).toEqual([]);
  });

  it("özet taşımayan kayıtlı tur boş sonuçla okunur, cümlesi kalır", () => {
    const state = threadReducer(initialState, {
      type: "load",
      conversation: { id: "kon1" },
      turns: [{ n: 1, question: "Kimler?", status: "failed", answer_text: "Veritabanına ulaşılamadı.", summary: null }],
    });
    expect(state.turns[0].summary).toEqual({
      columns: [],
      row_count: 0,
      rows: [],
      facts: [],
      chart_kind: null,
      context: null,
      clarification: null,
    });
    expect(state.turns[0].answer_text).toBe("Veritabanına ulaşılamadı.");
  });

  it("soru bekleyen tur ekler, önceki son tur katlanır", () => {
    const state = loaded({ type: "ask", question: "Ya Ağustos?" });
    expect(state.turns).toHaveLength(3);
    expect(state.turns[2]).toMatchObject({
      n: 3,
      question: "Ya Ağustos?",
      choice: null,
      status: "loading",
      answer_text: "",
      sql: null,
      audit_id: null,
      payload: null,
      stored: false,
      pending: true,
      expanded: false,
      collapsed: false,
    });
    expect(state.turns[1].collapsed).toBe(true);
  });

  it("bekleyen turun cevabı aynı tura yerleşir, konuşma kimliği yükten gelir", () => {
    const state = loaded({ type: "ask", question: "Bu müşteri kaç sipariş verdi?", choice: "C1 (A)" }, { type: "receive", payload: ANSWERED });
    expect(state.turns).toHaveLength(2);
    const turn = state.turns[1];
    expect({ n: turn.n, status: turn.status, choice: turn.choice, pending: turn.pending, stored: turn.stored }).toEqual({
      n: 2,
      status: "answered",
      choice: "C1 (A)",
      pending: false,
      stored: false,
    });
    expect(turn.answer_text).toBe("C1 müşterisinin 12 siparişi var.");
    expect(turn.audit_id).toBe("aa3");
    expect(turn.payload).toBe(ANSWERED);
    expect(turn.summary.rows).toEqual([[12]]);
    expect(turn.summary.chart_kind).toBe("bar");
    expect(turn.summary.context.line).toBe("Önceki cevaptan: müşteri C1 (A)");
    expect(turn.collapsed).toBe(false);
  });

  it("seçim bekleyen netleştirme turunu yerinde tamamlar, yeni tur açılmaz", () => {
    const waiting = loaded({ type: "ask", question: "Bu müşteri kaç sipariş verdi?", choice: "C1 (A)" });
    expect(waiting.turns).toHaveLength(2);
    expect({ n: waiting.turns[1].n, status: waiting.turns[1].status, pending: waiting.turns[1].pending }).toEqual({
      n: 2,
      status: "loading",
      pending: true,
    });
    const done = threadReducer(waiting, { type: "receive", payload: ANSWERED });
    expect(done.turns).toHaveLength(2);
    expect(done.turns[1].status).toBe("answered");
  });

  it("seçim başka bir sorunun şıkkıysa yeni tur eklenir", () => {
    const state = loaded({ type: "ask", question: "Başka bir soru?", choice: "C1 (A)" });
    expect(state.turns).toHaveLength(3);
    expect(state.turns[2].n).toBe(3);
    expect(state.turns[2].choice).toBe("C1 (A)");
  });

  it("cevaplı turun ardından seçimli soru da yeni turdur", () => {
    const answered = threadReducer(
      threadReducer(initialState, { type: "load", conversation: { id: "kon1" }, turns: [STORED[0]] }),
      { type: "ask", question: "Eylül satışı ne kadar?", choice: "Net satış" },
    );
    expect(answered.turns).toHaveLength(2);
    expect(answered.turns[1].n).toBe(2);
  });

  it("ilk soru konuşmayı açar: kimlik yükten okunur, numara 1", () => {
    const state = threadReducer(threadReducer(initialState, { type: "ask", question: "Kimler?" }), {
      type: "receive",
      payload: { ...ANSWERED, conversation_id: "yeni1", turn: 1, choice: null },
    });
    expect(state.conversationId).toBe("yeni1");
    expect(state.turns).toHaveLength(1);
    expect(state.turns[0].n).toBe(1);
  });

  it("başarısız yük turun cümlesini hatadan kurar", () => {
    const state = threadReducer(threadReducer(initialState, { type: "ask", question: "Kimler?" }), {
      type: "receive",
      payload: { status: "failed", question: "Kimler?", answer_text: "", error: { kind: "sql", message: "Kolon yok." }, turn: 1 },
    });
    expect(state.turns[0].status).toBe("failed");
    expect(state.turns[0].answer_text).toBe("Kolon yok.");
    expect(state.turns[0].summary.rows).toEqual([]);
  });

  it("yanıt gelmeden kopan bağlantı bekleyen turu başarısız yapar", () => {
    const state = loaded({ type: "ask", question: "Ya Ağustos?" }, { type: "fail", kind: "network", message: "Sunucuya ulaşılamadı" });
    expect(state.turns).toHaveLength(3);
    expect({ status: state.turns[2].status, pending: state.turns[2].pending, answer_text: state.turns[2].answer_text }).toEqual({
      status: "failed",
      pending: false,
      answer_text: "Sunucuya ulaşılamadı",
    });
    expect(state.turns[0].answer_text).toBe("Eylül satışı 8.910 adet.");
  });

  it("bekleyen tur yoksa receive ve fail listeye dokunmaz", () => {
    const state = threadReducer(initialState, { type: "load", conversation: { id: "kon1" }, turns: [STORED[0]] });
    expect(threadReducer(state, { type: "receive", payload: ANSWERED })).toBe(state);
    expect(threadReducer(state, { type: "fail", message: "x" })).toBe(state);
  });

  it("aç/kapat yalnızca o turun katlanmasını çevirir, son tur hiç katlanmaz", () => {
    const state = loaded();
    const open = threadReducer(state, { type: "expand", n: 1 });
    expect(open.turns[0].expanded).toBe(true);
    expect(open.turns[0].collapsed).toBe(false);
    expect(open.turns[1].collapsed).toBe(false);
    expect(threadReducer(open, { type: "expand", n: 1 }).turns[0].collapsed).toBe(true);
    expect(threadReducer(state, { type: "expand", n: 2 }).turns[1].collapsed).toBe(false);
  });

  it("reset yeni konuşma için akışı boşaltır ve başlangıç durumu bozulmaz", () => {
    const used = loaded({ type: "ask", question: "Ya Ağustos?" });
    expect(threadReducer(used, { type: "reset" })).toEqual({ conversationId: null, turns: [] });
    expect(initialState.turns).toEqual([]);
    expect(used.turns).toHaveLength(3);
  });

  it("tanınmayan eylem durumu olduğu gibi bırakır", () => {
    const state = loaded();
    expect(threadReducer(state, { type: "bilinmeyen" })).toBe(state);
  });
});
