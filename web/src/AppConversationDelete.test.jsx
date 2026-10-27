// @vitest-environment jsdom
// Konuşmayı kenar çubuğundan silmek adres, akış ve sonraki sorunun kimliği işidir: SSR bunları
// çalıştırmaz, o yüzden jsdom'da App gerçekten monte ediliyor. Ağ ve onay kutusu sahte — hangi
// konuşmanın silineceğini ve silinenin açık olup olmadığını test kuruyor.
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
  conversationDelete: vi.fn(),
  conversationGet: vi.fn(),
  conversationsList: vi.fn(),
  examples: vi.fn(),
  health: vi.fn(),
  history: vi.fn(),
  replay: vi.fn(),
  rulesList: vi.fn(),
  savedList: vi.fn(),
}));

const X = "3f2a9c0d1e4b4a7f8c6d5e2b1a0f9e8d";
const Y = "b7e1c4a9d0f24c6e8a3b5d7f1c0e9a24";

// Depodan gelen tur (Contracts "StoredTurn"): özet saklandığı kadardır, yük hiç yoktur.
function storedTurn(n) {
  return {
    n,
    question: `Eylül satışı ne kadar? ${n}`,
    choice: null,
    status: "answered",
    sql: "SELECT SUM(STHAR_GCMIK) FROM TBLSTHAR",
    answer_text: `Eylül 2026 satışı ${n}.`,
    audit_id: `aa${n}`,
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

// Kenar çubuğunun listesi: hem açık konuşma (X) hem başka bir konuşma (Y) silinebilir olmalı.
const LIST = [
  { id: X, title: "Eylül satışı ne kadar?", dataset: "wwi", created_at: "", updated_at: "", turns: 1 },
  { id: Y, title: "En çok satan 5 ürün", dataset: "wwi", created_at: "", updated_at: "", turns: 1 },
];

let container;
let root;

function mount() {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  act(() => root.render(<App />));
  return container;
}

// Cevap ve adres değişimi birer promise zinciri: ikisi de beklenir.
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

async function remove(id) {
  await act(async () => {
    container.querySelector(`[data-conversation-delete="${id}"]`).click();
  });
  await settle();
}

beforeEach(() => {
  window.location.hash = "#/";
  api.health.mockResolvedValue(null);
  api.examples.mockResolvedValue({ examples: [] });
  api.rulesList.mockResolvedValue({ rules: [] });
  api.savedList.mockResolvedValue({ saved: [] });
  api.history.mockResolvedValue({ history: [] });
  api.conversationsList.mockResolvedValue({ conversations: LIST });
  api.conversationDelete.mockResolvedValue({ deleted: true });
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  root = undefined;
  container = undefined;
  window.location.hash = "#/";
  vi.restoreAllMocks();
  vi.clearAllMocks();
});

describe("açık konuşmayı silmek", () => {
  it("silinen konuşma akışı boşatır, kök adrese döner ve sıradaki soru kimliksiz koşar", async () => {
    window.location.hash = `#/c/${X}`;
    api.conversationGet.mockResolvedValue({ conversation: { id: X }, turns: [storedTurn(1)] });
    api.ask.mockResolvedValue({ ...answered, question: "Ya Ağustos?", turn: 1, conversation_id: null, audit_id: "aa9" });
    const app = mount();
    await settle();

    // Konuşma açık: bir tur var, adres #/c/X.
    expect(app.querySelectorAll(".turn")).toHaveLength(1);
    expect(window.location.hash).toBe(`#/c/${X}`);

    await remove(X);

    expect(api.conversationDelete).toHaveBeenCalledWith(X);
    expect(app.querySelectorAll(".turn")).toHaveLength(0);
    expect(window.location.hash).toBe("#/");

    // Silinmiş konuşmanın kimliği bir daha soruyla gitmez: sıradaki soru yeni bir konuşma açar.
    type("Ya Ağustos?");
    await act(async () => app.querySelector("#ask-button").click());
    await settle();

    expect(api.ask.mock.calls.at(-1)[0].conversation_id ?? null).toBeNull();
  });

  it("başka bir konuşmayı silmek açık akışa ve adrese dokunmaz", async () => {
    window.location.hash = `#/c/${X}`;
    api.conversationGet.mockResolvedValue({ conversation: { id: X }, turns: [storedTurn(1)] });
    const app = mount();
    await settle();

    expect(app.querySelectorAll(".turn")).toHaveLength(1);

    await remove(Y);

    expect(api.conversationDelete).toHaveBeenCalledWith(Y);
    expect(app.querySelectorAll(".turn")).toHaveLength(1);
    expect(window.location.hash).toBe(`#/c/${X}`);
  });
});
