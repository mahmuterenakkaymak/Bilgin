// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// @vitest-environment jsdom
// Dil düğmesi tek başına bir ekran değil, giriş kartıyla başlığın ortak tek kontrolü: hangisinin
// seçili olduğu, seçimin nereye yazıldığı ve oturum varsa sunucuya da söylenmesi burada okunur.
// Ağ katmanı sahte — düğmenin sunucuya tek sözü `setMyLang`, ölçülen de o sözün edilip edilmediği.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n/index.js";
import * as api from "../lib/api.js";
import LangToggle from "./LangToggle.jsx";

vi.mock("../lib/api.js", () => ({
  setApiLang: vi.fn(),
  setMyLang: vi.fn(() => Promise.resolve({})),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const ADMIN = { username: "admin", role: "admin" };

let container;
let root;

async function mount(node) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => {
    root.render(node);
  });
  return container;
}

async function click(node) {
  await act(async () => {
    node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  });
}

const toggle = (scope) => scope.querySelector("#lang-toggle");
const button = (scope, code) => scope.querySelector(`#lang-toggle button[data-lang="${code}"]`);
// Düğme dili kendi seçmez, provider'dan okur: test de açılışı gibi Türkçe bir ağacın içine kurar.
const inTurkish = (props = {}) => (
  <I18nProvider lang="tr">
    <LangToggle {...props} />
  </I18nProvider>
);

afterEach(() => {
  act(() => root.unmount());
  container?.remove();
  container = undefined;
  root = undefined;
  localStorage.clear();
  document.documentElement.lang = "tr";
  vi.clearAllMocks();
});

describe("dil düğmesi", () => {
  it("iki seçenek de kendi koduyla boyanır, seçili olanı basılı durur", async () => {
    const app = await mount(inTurkish());
    expect(toggle(app).getAttribute("aria-label")).toBe("Arayüz dili");
    expect(button(app, "tr").textContent).toBe("TR");
    expect(button(app, "en").textContent).toBe("EN");
    expect(button(app, "tr").getAttribute("aria-pressed")).toBe("true");
    expect(button(app, "en").getAttribute("aria-pressed")).toBe("false");
    expect(button(app, "en").getAttribute("aria-label")).toBe("İngilizce");
  });

  it("EN'e basmak aynı ağacı çevirir: yeniden yükleme yok, etiketler İngilizce", async () => {
    const app = await mount(inTurkish());
    const group = toggle(app);

    await click(button(app, "en"));

    expect(group.isConnected).toBe(true);
    expect(toggle(app).getAttribute("aria-label")).toBe("Interface language");
    expect(button(app, "tr").getAttribute("aria-label")).toBe("Turkish");
    expect(button(app, "en").getAttribute("aria-pressed")).toBe("true");
    expect(button(app, "tr").getAttribute("aria-pressed")).toBe("false");
  });

  it("seçim yerelde, kök nitelikte ve istek başlığında karşılık bulur", async () => {
    const app = await mount(inTurkish());

    await click(button(app, "en"));

    expect(localStorage.getItem("bilgin.lang")).toBe("en");
    expect(document.documentElement.lang).toBe("en");
    expect(api.setApiLang).toHaveBeenCalledWith("en");
  });

  it("oturum varsa tercih sunucunun kendi kaydına da yazılır", async () => {
    const app = await mount(inTurkish({ user: ADMIN }));

    await click(button(app, "en"));

    expect(api.setMyLang).toHaveBeenCalledWith("en");
    expect(localStorage.getItem("bilgin.lang")).toBe("en");
  });

  it("oturum yokken (giriş kartı) tercih yalnız yerelde kalır", async () => {
    const app = await mount(inTurkish());

    await click(button(app, "en"));

    expect(api.setMyLang).not.toHaveBeenCalled();
    expect(localStorage.getItem("bilgin.lang")).toBe("en");
  });

  it("seçili dile basmak hiçbir şeyi değiştirmez", async () => {
    const app = await mount(inTurkish({ user: ADMIN }));

    await click(button(app, "tr"));

    expect(api.setMyLang).not.toHaveBeenCalled();
    expect(localStorage.getItem("bilgin.lang")).toBeNull();
    expect(button(app, "tr").getAttribute("aria-pressed")).toBe("true");
  });
});
