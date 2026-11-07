// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// @vitest-environment jsdom
// Kayıtlı turun "Yeniden çalıştır"ı yeni bir tur açmaz: cevap koşumun ait olduğu tura yerleşir ve
// numarasını korur (PLAN R7-15, M23 review 1). App gerçekten monte ediliyor; ağ sahte.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import answered from "./fixtures/answered.json";
import App from "./App.jsx";
import * as api from "./lib/api.js";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("./lib/api.js", async (importOriginal) => ({
  ...(await importOriginal()),
  ask: vi.fn(),
  conversationGet: vi.fn(),
  examples: vi.fn(),
  health: vi.fn(),
  history: vi.fn(),
  replay: vi.fn(),
  rulesList: vi.fn(),
  savedList: vi.fn(),
}));

const ID = "3f2a9c0d1e4b4a7f8c6d5e2b1a0f9e8d";

// Depodan gelen tur (Contracts "StoredTurn"): özet saklandığı kadardır, tam kart için yük yoktur.
function stored(n, question, auditId) {
  return {
    n,
    question,
    choice: null,
    status: "answered",
    sql: "SELECT 1",
    answer_text: `${question} - kayıtlı özet.`,
    audit_id: auditId,
    created_at: "2026-10-20T09:00:00+00:00",
    summary: {
      columns: ["SATIS"],
      row_count: 1,
      rows: [[8910]],
      facts: [],
      chart_kind: null,
      context: null,
      clarification: null,
    },
  };
}

// /api/replay'in yükü konuşmaya tur yazmaz, o yüzden turn/conversation_id TAŞIMAZ - R7-15 hatası
// tam buradan doğuyordu. Cevabın kendisi gerçekçi olsun diye fixture'dan.
function replayPayload(question, auditId) {
  const payload = { ...answered, question, audit_id: auditId };
  delete payload.turn;
  delete payload.conversation_id;
  return payload;
}

let container;
let root;

function mount() {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  act(() => root.render(<App />));
  return container;
}

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function type(question) {
  const box = container.querySelector("#question");
  const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set;
  act(() => {
    setValue.call(box, question);
    box.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function ask(question) {
  type(question);
  await act(async () => container.querySelector("#ask-button").click());
  await settle();
}

beforeEach(() => {
  window.location.hash = "#/";
  api.health.mockResolvedValue(null);
  api.examples.mockResolvedValue({ examples: [] });
  api.rulesList.mockResolvedValue({ rules: [] });
  api.savedList.mockResolvedValue({ saved: [] });
  api.history.mockResolvedValue({ history: [] });
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  root = undefined;
  container = undefined;
  window.location.hash = "#/";
  vi.clearAllMocks();
});

describe("kayıtlı turu yeniden çalıştırmak", () => {
  it("yeni tur açmaz: cevap yeniden koşulan turun kendisine yerleşir, takip eden soru numarasını korur", async () => {
    window.location.hash = `#/c/${ID}`;
    api.conversationGet.mockResolvedValue({
      conversation: { id: ID },
      turns: [stored(1, "Eylül satışı ne kadar?", "aa1"), stored(2, "Ya Ağustos?", "aa2")],
    });
    api.replay.mockResolvedValue(replayPayload("Eylül satışı ne kadar?", "aa1"));
    const app = mount();
    await settle();

    expect(app.querySelectorAll(".turn")).toHaveLength(2);

    await act(async () => app.querySelector('[data-turn-replay="1"]').click());
    await settle();

    // Kayıtlı SQL /api/replay'den geçer; tur numarası 1'in yerini başka bir tur almaz.
    expect(api.replay).toHaveBeenCalledTimes(1);
    expect(api.replay).toHaveBeenCalledWith("aa1");
    expect(app.querySelectorAll(".turn")).toHaveLength(2);
    // Tam kart koşumun ait olduğu turun içinde belirir; kayıtlı turun "Yeniden çalıştır"ı kalkar.
    expect(app.querySelectorAll(".turn")[0].querySelector("#answer-card")).not.toBeNull();
    expect(app.querySelector('[data-turn-replay="1"]')).toBeNull();
    expect(app.textContent).toContain("Siyah Çay 500 g");
    // Konuşma baştan okunmaz, adres değişmez: ne bir kimlik gönderildi ne de yükten kimlik benimsendi.
    expect(api.conversationGet).toHaveBeenCalledTimes(1);
    expect(window.location.hash).toBe(`#/c/${ID}`);

    // Takip eden soru açık konuşmanın kimliğiyle koşar ve üçüncü turun numarasını alır.
    api.ask.mockResolvedValue({ ...answered, question: "Ekim?", turn: 3, conversation_id: ID, audit_id: "aa3" });
    await ask("Ekim?");

    expect(api.ask).toHaveBeenCalledWith(expect.objectContaining({ conversation_id: ID }));
    expect(app.querySelectorAll(".turn")).toHaveLength(3);
    expect(Array.from(app.querySelectorAll(".turn-question"), (node) => node.textContent)).toEqual([
      "Eylül satışı ne kadar?",
      "Ya Ağustos?",
      "Ekim?",
    ]);
    // Yeniden koşulan tur ile takip eden soru aynı numarayı taşımaz: ikisi de kendi tam kartını açar.
    expect(app.querySelectorAll("#answer-card")).toHaveLength(2);
  });
});
