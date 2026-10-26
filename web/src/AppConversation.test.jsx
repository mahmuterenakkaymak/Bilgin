// @vitest-environment jsdom
// Konuşma adres, olay ve iki soru arasında taşınan kimlik işidir: SSR hiçbiri çalıştırmaz, o
// yüzden dosyanın ortamı jsdom ve App gerçekten monte ediliyor. Ağ sahte — hangi cevabın hangi
// sırayla döneceğini test kuruyor.
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

// Cevap yükü gerçekçi olsun diye fixture'dan: grafiği yok, o yüzden jsdom'da çizim de koşmaz.
function payload(n, question) {
  return { ...answered, question, turn: n, conversation_id: ID, audit_id: `aa${n}` };
}

// Depodan gelen tur (Contracts "StoredTurn"): özet saklandığı kadardır, yük hiç yoktur.
const STORED = {
  n: 1,
  question: "Eylül satışı ne kadar?",
  choice: null,
  status: "answered",
  sql: "SELECT SUM(STHAR_GCMIK) FROM TBLSTHAR",
  answer_text: "Eylül 2026 satışı 8.910 adet.",
  audit_id: "aa1",
  created_at: "2026-10-20T09:00:00+00:00",
  summary: {
    columns: ["SATIS"],
    row_count: 1,
    rows: [[8910]],
    facts: [],
    chart_kind: "bar",
    context: null,
    clarification: null,
  },
};

let container;
let root;

function mount() {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  act(() => root.render(<App />));
  return container;
}

// Cevap bir promise zinciri, adresin değişmesi (hashchange) ayrı bir görev: ikisi de beklenir.
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

// Kutu React'ın denetlediği alan: değer onun kendi kurucusuyla yazılır, yoksa onChange görmez.
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

describe("konuşma akışı", () => {
  it("ikinci soru açık konuşmanın kimliğiyle koşar ve akışta iki tur okunur", async () => {
    api.ask
      .mockResolvedValueOnce(payload(1, "Eylül satışı ne kadar?"))
      .mockResolvedValueOnce(payload(2, "Ya Ağustos?"));
    const app = mount();

    await ask("Eylül satışı ne kadar?");
    await ask("Ya Ağustos?");

    // İlk soru konuşmayı açar: kimlik ondan sonraki her soruyla gider.
    expect(api.ask.mock.calls.map(([body]) => body.conversation_id ?? null)).toEqual([null, ID]);
    expect(Array.from(app.querySelectorAll(".turn-question"), (node) => node.textContent)).toEqual([
      "Eylül satışı ne kadar?",
      "Ya Ağustos?",
    ]);
    expect(app.querySelectorAll(".turn")).toHaveLength(2);
    // Canlı cevap akışın kendisidir: adres açılsa da konuşma baştan okunmaz.
    expect(api.conversationGet).not.toHaveBeenCalled();
    expect(window.location.hash).toBe(`#/c/${ID}`);
  });

  it("Yeni konuşma akışı boşatır ve kök adrese döner", async () => {
    api.ask.mockResolvedValue(payload(1, "Eylül satışı ne kadar?"));
    const app = mount();

    await ask("Eylül satışı ne kadar?");
    expect(app.querySelectorAll(".turn")).toHaveLength(1);

    await act(async () => app.querySelector("#new-conversation").click());
    await settle();

    expect(app.querySelectorAll(".turn")).toHaveLength(0);
    expect(app.querySelector("#new-conversation")).toBeNull();
    expect(app.querySelector("#question").value).toBe("");
    expect(app.textContent).toContain("Verinize Türkçe soru sorun");
    expect(window.location.hash).toBe("#/");
  });
});

describe("konuşmayı açmak", () => {
  it("#/c/<id> ile yenileyince akış conversationGet ile gelir, hiçbir soru koşulmaz", async () => {
    window.location.hash = `#/c/${ID}`;
    api.conversationGet.mockResolvedValue({ conversation: { id: ID }, turns: [STORED] });
    const app = mount();

    await settle();

    expect(api.conversationGet).toHaveBeenCalledWith(ID);
    expect(api.ask).not.toHaveBeenCalled();
    expect(api.replay).not.toHaveBeenCalled();
    expect(app.querySelectorAll(".turn")).toHaveLength(1);
    expect(app.textContent).toContain("Eylül 2026 satışı 8.910 adet.");
    expect(app.textContent).toContain("Tam tablo ve grafik için yeniden çalıştırın.");
    expect(app.querySelector("#new-conversation")).not.toBeNull();
    // Kutu son turun altında: akışın kendisi soru ekranıdır.
    const thread = app.querySelector("#thread");
    expect(thread.compareDocumentPosition(app.querySelector("#question")) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
      Node.DOCUMENT_POSITION_FOLLOWING,
    );
  });

  it("olmayan konuşma cümlesiyle kök adrese düşürür", async () => {
    window.location.hash = "#/c/yokboylebirkimlik";
    api.conversationGet.mockRejectedValue(new api.ApiError(404, "Konuşma bulunamadı."));
    const app = mount();

    await settle();

    expect(app.querySelector("#route-note").textContent).toContain("Konuşma bulunamadı.");
    expect(window.location.hash).toBe("#/");
    expect(app.querySelectorAll(".turn")).toHaveLength(0);
  });
});
