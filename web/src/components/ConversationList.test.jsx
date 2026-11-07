// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// @vitest-environment jsdom
// Konuşma listesi tıklama ve silme işidir: satır adrese yazar, silme onay ister. SSR bunları
// çalıştırmaz, o yüzden jsdom'da gerçekten monte ediliyor. Ağ sahte — silme çağrısını test kuruyor.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ConversationList from "./ConversationList.jsx";
import * as api from "../lib/api.js";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../lib/api.js", async (importOriginal) => ({
  ...(await importOriginal()),
  conversationDelete: vi.fn(),
}));

const ID = "3f2a9c0d1e4b4a7f8c6d5e2b1a0f9e8d";

const CONVERSATIONS = [
  { id: ID, title: "Eylül satışı ne kadar?", dataset: "wwi", created_at: "", updated_at: "", turns: 3 },
  { id: "kisa", title: "En çok satan 5 ürün", dataset: "wwi", created_at: "", updated_at: "", turns: 1 },
];

let container;
let root;

function mount(props) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  act(() => root.render(<ConversationList {...props} />));
  return container;
}

beforeEach(() => {
  window.location.hash = "#/";
  vi.spyOn(window, "confirm");
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

describe("ConversationList", () => {
  it("boş liste kendi cümlesiyle kurulur", () => {
    const el = mount({ conversations: [] });
    expect(el.querySelector("#conversation-list")).not.toBeNull();
    expect(el.textContent).toContain("Henüz konuşma yok.");
    expect(el.querySelectorAll(".side-item")).toHaveLength(0);
  });

  it("konuşma alanı hiç gelmese de boş hâl kurulur", () => {
    const el = mount({});
    expect(el.querySelector("#conversation-list")).not.toBeNull();
    expect(el.textContent).toContain("Henüz konuşma yok.");
  });

  it("satır başlığı, tur sayısını ve silme düğmesini taşır", () => {
    const el = mount({ conversations: CONVERSATIONS });
    const items = el.querySelectorAll("#conversation-list .side-item");
    expect(items).toHaveLength(2);
    expect(el.textContent).toContain("Eylül satışı ne kadar?");
    expect(el.textContent).toContain("3 tur");
    expect(el.querySelector("[data-conversation-delete]")?.dataset.conversationDelete).toBe(ID);
    expect(el.querySelectorAll("[data-conversation-delete]")).toHaveLength(2);
  });

  it("satıra gelmek #/c/<id>ye gider, hiçbir ask/replay çağırmaz", () => {
    const el = mount({ conversations: CONVERSATIONS });
    act(() => el.querySelector(".side-text").click());
    expect(window.location.hash).toBe(`#/c/${ID}`);
    expect(api.conversationDelete).not.toHaveBeenCalled();
  });

  it("silme onay ister; onaylanırsa konuşmayı siler ve listeyi tazeler", async () => {
    const onRemoved = vi.fn();
    api.conversationDelete.mockResolvedValue({ deleted: true });
    window.confirm.mockReturnValue(true);
    const el = mount({ conversations: CONVERSATIONS, onRemoved });

    await act(async () => {
      el.querySelector("[data-conversation-delete]").click();
    });

    expect(window.confirm).toHaveBeenCalled();
    expect(api.conversationDelete).toHaveBeenCalledWith(ID);
    expect(onRemoved).toHaveBeenCalled();
  });

  it("onaylanmazsa hiçbir şey silinmez", async () => {
    const onRemoved = vi.fn();
    window.confirm.mockReturnValue(false);
    const el = mount({ conversations: CONVERSATIONS, onRemoved });

    await act(async () => {
      el.querySelector("[data-conversation-delete]").click();
    });

    expect(window.confirm).toHaveBeenCalled();
    expect(api.conversationDelete).not.toHaveBeenCalled();
    expect(onRemoved).not.toHaveBeenCalled();
  });

  it("silme başarısız olursa cümlesi listede görünür, tazeleme çağrılmaz", async () => {
    const onRemoved = vi.fn();
    api.conversationDelete.mockRejectedValue(new api.ApiError(500, "Sunucu hatası."));
    window.confirm.mockReturnValue(true);
    const el = mount({ conversations: CONVERSATIONS, onRemoved });

    await act(async () => {
      el.querySelector("[data-conversation-delete]").click();
    });

    expect(el.querySelector(".side-note")?.textContent).toContain("Sunucu hatası.");
    expect(onRemoved).not.toHaveBeenCalled();
  });

  it("iki turlu konuşma satırı son sorusuyla adlanır, ilk soru titleda durur", () => {
    const el = mount({
      conversations: [
        {
          id: ID,
          title: "Eylül satışı ne kadar?",
          last_question: "Bunda Ankara'nın payı kaç?",
          dataset: "wwi",
          created_at: "",
          updated_at: "",
          turns: 2,
        },
      ],
    });

    const row = el.querySelector("#conversation-list .side-text");
    expect(row.querySelector(".side-label")?.textContent).toBe("Bunda Ankara'nın payı kaç?");
    expect(row.getAttribute("title")).toBe("Eylül satışı ne kadar?");
  });

  it("liste kendi içinde kayar: alt bölümler erişilebilir kalsın diye", () => {
    const el = mount({ conversations: CONVERSATIONS });
    expect(el.querySelector("#conversation-list").classList.contains("side-scroll")).toBe(true);
  });
});
