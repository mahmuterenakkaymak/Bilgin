// @vitest-environment jsdom
// Kutunun temizlenmesi bir olay işidir: cevap gelince kutu boşalmalı, netleştirme ve koşmayan
// soru ise kutuda kalmalı ("Soruyu değiştir" oradaki metni düzenler). Ağ sahte — hangi yükün
// döneceğini test kuruyor.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import answered from "./fixtures/answered.json";
import clarification from "./fixtures/clarification.json";
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
  start: vi.fn(),
}));

const ID = "3f2a9c0d1e4b4a7f8c6d5e2b1a0f9e8d";
const QUESTION = "Eylül satışı ne kadar?";

// Yükler gerçekçi olsun diye fixture'lardan: ikisinin de grafiği yok, o yüzden jsdom'da çizim koşmaz.
function answeredPayload() {
  return { ...answered, question: QUESTION, turn: 1, conversation_id: ID, audit_id: "aa1" };
}

function clarificationPayload() {
  return { ...clarification, question: QUESTION, turn: 1, conversation_id: ID };
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
  api.start.mockResolvedValue({ cards: [] });
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  root = undefined;
  container = undefined;
  window.location.hash = "#/";
  vi.clearAllMocks();
});

describe("soru kutusu", () => {
  it("cevaplanan soru kutuyu boşaltır: soru akışta kalır, kutuda kalmaz", async () => {
    api.ask.mockResolvedValue(answeredPayload());
    const app = mount();

    await ask(QUESTION);

    expect(app.querySelectorAll(".turn-question")).toHaveLength(1);
    expect(app.querySelector("#question").value).toBe("");
    expect(app.querySelector("#question").placeholder).toBe("Sorunuzu yazın");
  });

  it("netleşen soru kutuda durur: soruyu değiştirme onu düzenler", async () => {
    api.ask.mockResolvedValue(clarificationPayload());
    const app = mount();

    await ask(QUESTION);

    expect(app.querySelector("#question").value).toBe(QUESTION);
  });

  it("koşmayan soru kutuda durur: kullanıcı yeniden deneyebilir", async () => {
    api.ask.mockRejectedValue(new api.ApiError(500, "Cevap üretilemedi."));
    const app = mount();

    await ask(QUESTION);

    expect(app.querySelector("#question").value).toBe(QUESTION);
  });

  it("Yeni konuşma kutuyu boşaltır", async () => {
    api.ask.mockResolvedValue(answeredPayload());
    const app = mount();

    await ask(QUESTION);
    type("Ya Ağustos?");
    await act(async () => app.querySelector("#new-conversation").click());
    await settle();

    expect(app.querySelector("#question").value).toBe("");
  });
});
