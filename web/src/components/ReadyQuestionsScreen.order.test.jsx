// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// @vitest-environment jsdom
// Öneri kuyruğunun düzeni (M28 review 4): her rol grubunda onay bekleyenler öne geçer, "Yalnız
// bekleyenler" süzgeci onaylı kartları belgeden kaldırır ve halini adrese yazar. Sıra ile süzgeç
// işareti indirgeyiciden okunduğu için gruplar SSR ile; tıklama ve adres jsdom'da koşar. Kartların
// kimliği (data-ready-*) korunur — onaylı satır tek satıra inse de aç/düzenle/sil yerinde kalır.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../lib/api.js";
import ReadyQuestionsScreen from "./ReadyQuestionsScreen.jsx";

vi.mock("../lib/api.js", async (importOriginal) => ({
  ...(await importOriginal()),
  readyList: vi.fn(),
  readyUpdate: vi.fn(),
  readyRemove: vi.fn(),
  readySuggest: vi.fn(),
  readySuggestStatus: vi.fn(),
  startOpen: vi.fn(),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function ready(over) {
  return {
    id: 1,
    dataset: "wwi",
    business_role: "satis",
    title: "Başlık",
    question: "Soru cümlesi?",
    sql: "SELECT 1",
    display: "number",
    position: 1,
    created_by: "admin",
    approved: true,
    audit_id: "a1",
    created_at: "2026-10-25T09:00:00+00:00",
    ...over,
  };
}

// Karışık liste: Satış grubunda onaylı/bekleyen iç içe, Herkes grubunda birer tane.
const ROWS = [
  ready({ id: 1, business_role: "satis", title: "Satış onaylı A", approved: true, position: 1 }),
  ready({ id: 2, business_role: "satis", title: "Satış bekleyen B", approved: false, position: 2 }),
  ready({ id: 3, business_role: "satis", title: "Satış onaylı C", approved: true, position: 3 }),
  ready({ id: 4, business_role: "satis", title: "Satış bekleyen D", approved: false, position: 4 }),
  ready({ id: 5, business_role: "*", title: "Herkes onaylı E", approved: true, position: 1 }),
  ready({ id: 6, business_role: "*", title: "Herkes bekleyen F", approved: false, position: 2 }),
];
const PENDING = ["2", "4", "6"];
const APPROVED = ["1", "3", "5"];

function render(node) {
  return renderToStaticMarkup(node)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&");
}

// Her grubun kendi satır sırası: { rol: [id, ...] }.
function orderPerGroup(html) {
  const parts = html.split(/data-ready-group="([^"]*)"/);
  const result = {};
  for (let i = 1; i < parts.length; i += 2) {
    const body = parts[i + 1] || "";
    result[parts[i]] = [...body.matchAll(/data-ready-id="([^"]*)"/g)].map((match) => match[1]);
  }
  return result;
}

let container;
let root;

async function mount() {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => {
    root.render(<ReadyQuestionsScreen rows={ROWS} />);
  });
  return container;
}

async function click(node) {
  await act(async () => {
    node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  });
}

beforeEach(() => {
  window.location.hash = "#/hazir-sorular";
});

afterEach(() => {
  if (root) {
    act(() => root.unmount());
    root = undefined;
  }
  container?.remove();
  container = undefined;
  window.location.hash = "#/";
  vi.clearAllMocks();
});

describe("Sıra: bekleyenler önce", () => {
  it("her rol grubunda onay bekleyen kartlar onaylıların önüne geçer", () => {
    const groups = orderPerGroup(render(<ReadyQuestionsScreen rows={ROWS} />));
    const approved = new Set(APPROVED);

    for (const [role, ids] of Object.entries(groups)) {
      let seenApproved = false;
      for (const id of ids) {
        if (approved.has(id)) seenApproved = true;
        else expect(seenApproved, `bekleyen ${id} ${role} grubunda bir onaylının ardında kaldı`).toBe(false);
      }
    }
    // Eşitlik bozulmaz: bekleyenler kendi aralarında, onaylılar kendi aralarında eski sırasında.
    expect(groups.satis).toEqual(["2", "4", "1", "3"]);
    expect(groups["*"]).toEqual(["6", "5"]);
  });
});

describe("Yalnız bekleyenler süzgeci", () => {
  it("açılınca onaylı kartlar belgeden kalkar, bekleyenler kalır, hal adres taşır", async () => {
    const app = await mount();
    expect(app.querySelector('[data-ready-id="1"]')).not.toBeNull();

    await click(app.querySelector("#ready-filter-pending"));

    for (const id of APPROVED) expect(app.querySelector(`[data-ready-id="${id}"]`)).toBeNull();
    for (const id of PENDING) expect(app.querySelector(`[data-ready-id="${id}"]`)).not.toBeNull();
    expect(window.location.hash).toContain("pending=1");
  });

  it("kapanca onaylı kartlar geri gelir, adres işaretini bırakır", async () => {
    const app = await mount();
    await click(app.querySelector("#ready-filter-pending"));
    await click(app.querySelector("#ready-filter-pending"));

    for (const id of APPROVED) expect(app.querySelector(`[data-ready-id="${id}"]`)).not.toBeNull();
    expect(window.location.hash).not.toContain("pending=1");
  });

  it("adreste işaret varsa ekran süzülmüş açılır — yenileme hali korur", async () => {
    window.location.hash = "#/hazir-sorular?pending=1";
    const app = await mount();

    for (const id of APPROVED) expect(app.querySelector(`[data-ready-id="${id}"]`)).toBeNull();
    for (const id of PENDING) expect(app.querySelector(`[data-ready-id="${id}"]`)).not.toBeNull();
  });
});

describe("Kartların kimlikleri kalır", () => {
  function rowHtml(id) {
    const html = render(<ReadyQuestionsScreen rows={[ROWS.find((row) => row.id === id)]} />);
    return html.match(/<li class="card ready-row"[\s\S]*?<\/li>/)[0];
  }

  it("onaysız kartta aç/onayla/düzenle/sil kendi kimliğiyle durur", () => {
    const row = rowHtml(2);
    for (const action of ["open", "approve", "edit", "delete"]) {
      expect(row).toContain(`data-ready-${action}="2"`);
    }
  });

  it("onaylı kart tek satıra inse de aç/düzenle/sil kimliklerini kaybetmez", () => {
    const row = rowHtml(1);
    expect(row).toContain('data-ready-approved="1"');
    for (const action of ["open", "edit", "delete"]) {
      expect(row).toContain(`data-ready-${action}="1"`);
    }
  });
});
