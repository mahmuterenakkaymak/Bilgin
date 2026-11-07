// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// @vitest-environment jsdom
// Cevabın pano işleri hem işaret hem olay ister: düğmelerin kimin için kurulduğu SSR ile,
// tıklaması, girdiği ve reddin cümlesi jsdom'da okunur. Grafikli yükler burada çizilmez —
// ChartView'ın efekti jsdom'da koşmaz, o yüzden kartın yükü grafiksizdir.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import answered from "../fixtures/answered.json";
import * as api from "../lib/api.js";
import AnswerCard from "./AnswerCard.jsx";
import ReadyQuestionForm from "./ReadyQuestionForm.jsx";

vi.mock("../lib/api.js", async (importOriginal) => ({
  ...(await importOriginal()),
  pinCard: vi.fn(),
  readyCreate: vi.fn(),
  readyUpdate: vi.fn(),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const noop = () => {};
const AUDIT = answered.audit_id;
const QUESTION = answered.question;

// Sözleşme "ready create body": sql yoktur, sunucu onu audit_id'nin kaydından alır.
const BODY = { title: QUESTION, question: QUESTION, display: "table", business_role: "*", audit_id: AUDIT };

// Tek sayılık cevap görünümü "number"a, grafiği olan "chart"a çevirir (suggest_display).
const NUMBER = { ...answered, columns: ["CIRO"], rows: [[191722.79]], row_count: 1 };
const CHART = { ...answered, chart: { type: "bar", option: { series: [] } } };

function render(node) {
  return renderToStaticMarkup(node)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&");
}

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

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function click(node) {
  await act(async () => {
    node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  });
}

// React kontrollü girdiye yazmak değeri yerleştirmeyi değil, yerel değiştiriciyi çağırmayı ister.
async function fill(node, value) {
  const setter = Object.getOwnPropertyDescriptor(node.constructor.prototype, "value").set;
  await act(async () => {
    setter.call(node, value);
    node.dispatchEvent(new Event("input", { bubbles: true }));
    node.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

afterEach(() => {
  if (root) {
    act(() => root.unmount());
    root = undefined;
  }
  container?.remove();
  container = undefined;
  vi.clearAllMocks();
});

describe("ReadyQuestionForm", () => {
  it("başlık ve soru cevabın sorusundan, görünüm yürüyen sonucun biçiminden gelir", async () => {
    const app = await mount(<ReadyQuestionForm payload={answered} />);
    expect(app.querySelector("#ready-title").value).toBe(QUESTION);
    expect(app.querySelector("#ready-question").value).toBe(QUESTION);
    expect(app.querySelector("#ready-display").value).toBe("table");
    expect(app.querySelector("#ready-role").value).toBe("*");
  });

  it("önerilen görünüm cevabın biçimini izler: tek sayı number, grafiği olan chart", async () => {
    const number = await mount(<ReadyQuestionForm payload={NUMBER} />);
    expect(number.querySelector("#ready-display").value).toBe("number");
    expect(number.textContent).toContain("Sonucun biçiminden önerilen: Tek sayı.");
    act(() => root.unmount());

    const chart = await mount(<ReadyQuestionForm payload={CHART} />);
    expect(chart.querySelector("#ready-display").value).toBe("chart");
  });

  it("rol seçenekleri Herkes ile iş rolleri, görünüm seçenekleri üç biçim", async () => {
    const app = await mount(<ReadyQuestionForm payload={answered} />);
    const options = (id) => Array.from(app.querySelectorAll(`#${id} option`), (node) => node.textContent);
    expect(options("ready-role")).toEqual([
      "Herkes",
      "Satış",
      "Satın alma",
      "Muhasebe",
      "Yönetim",
      "Genel",
    ]);
    expect(options("ready-display")).toEqual(["Tek sayı", "Grafik", "Tablo"]);
  });

  it("Kaydet sözleşme gövdesini POST eder; sql gitmez", async () => {
    api.readyCreate.mockResolvedValue({ ready_question: { id: 1 } });
    const app = await mount(<ReadyQuestionForm payload={answered} />);

    await click(app.querySelector("#ready-save"));
    await settle();

    expect(api.readyCreate).toHaveBeenCalledTimes(1);
    expect(api.readyCreate.mock.calls[0][0]).toEqual(BODY);
    expect(api.readyCreate.mock.calls[0][0]).not.toHaveProperty("sql");
  });

  it("düzenlenen başlık ve rol gövdeye yazılır", async () => {
    api.readyCreate.mockResolvedValue({ ready_question: { id: 1 } });
    const app = await mount(<ReadyQuestionForm payload={answered} />);

    await fill(app.querySelector("#ready-title"), "Net satış");
    await fill(app.querySelector("#ready-role"), "satis");
    await click(app.querySelector("#ready-save"));
    await settle();

    expect(api.readyCreate.mock.calls[0][0]).toEqual({ ...BODY, title: "Net satış", business_role: "satis" });
  });

  it("422'nin cümlesi formda okunur ve form açık kalır", async () => {
    api.readyCreate.mockRejectedValue(new api.ApiError(422, "Bu giriş bu kolonu göremez."));
    const app = await mount(<ReadyQuestionForm payload={answered} />);

    await click(app.querySelector("#ready-save"));
    await settle();

    expect(app.querySelector("#ready-error").textContent).toBe("Bu giriş bu kolonu göremez.");
    expect(app.querySelector("#ready-title")).not.toBeNull();
    expect(app.querySelector("#ready-save").disabled).toBe(false);
  });

  it("kayıt cümlesi kartı kimin panosuna eklediğini söyler", async () => {
    api.readyCreate.mockResolvedValue({ ready_question: { id: 1 } });
    const app = await mount(<ReadyQuestionForm payload={answered} />);

    await fill(app.querySelector("#ready-role"), "satis");
    await click(app.querySelector("#ready-save"));
    await settle();

    expect(app.querySelector("#ready-saved").textContent).toBe("Hazır soru eklendi: Satış için panoda.");
    expect(app.querySelector("#ready-title")).toBeNull();
  });

  it("Vazgeç formu kapatır", async () => {
    const canceled = vi.fn();
    const app = await mount(<ReadyQuestionForm payload={answered} onCancel={canceled} />);

    await click(app.querySelector("#ready-cancel"));

    expect(canceled).toHaveBeenCalledTimes(1);
  });
});

describe("AnswerCard — pano işleri", () => {
  const card = (props = {}) => render(<AnswerCard payload={answered} onSave={noop} {...props} />);

  it("Panoma ekle herkesin, Hazır soru yap yöneticinin düğmesidir", () => {
    const user = card();
    expect(user).toContain('id="pin-card"');
    expect(user).toContain(">Panoma ekle</button>");
    expect(user).not.toContain('id="make-ready"');

    const admin = card({ isAdmin: true });
    expect(admin).toContain('id="make-ready"');
    expect(admin).toContain(">Hazır soru yap</button>");
  });

  it("denetim kaydı olmayan cevapta panonun düğmeleri kurulmaz", () => {
    const html = card({ payload: { ...answered, audit_id: "" }, isAdmin: true });
    expect(html).not.toContain('id="pin-card"');
    expect(html).not.toContain('id="make-ready"');
    expect(html).toContain('id="save-question"');
  });

  it("kartın yeniden onayından gelince formun yerini güncelleme düğmesi alır", () => {
    const html = card({ isAdmin: true, reapproveId: 14 });
    expect(html).toContain('id="ready-reapprove"');
    expect(html).toContain(">Bu SQL ile güncelle</button>");
    expect(html).not.toContain('id="make-ready"');
  });

  it("Panoma ekle kaydı POST eder ve düğme eklendi diye okunur", async () => {
    api.pinCard.mockResolvedValue({ card: { id: 5 } });
    const app = await mount(<AnswerCard payload={answered} onSave={noop} />);

    await click(app.querySelector("#pin-card"));
    await settle();

    expect(api.pinCard).toHaveBeenCalledWith({ audit_id: AUDIT });
    expect(app.querySelector("#pin-card").textContent).toBe("Panoya eklendi");
    expect(app.querySelector("#pin-card").disabled).toBe(true);
  });

  it("kotanın 409 cümlesi kartın içinde okunur, cevabın kendisi yerinde kalır", async () => {
    api.pinCard.mockRejectedValue(new api.ApiError(409, "En fazla 6 kişisel kart ekleyebilirsiniz."));
    const app = await mount(<AnswerCard payload={answered} onSave={noop} />);

    await click(app.querySelector("#pin-card"));
    await settle();

    expect(app.textContent).toContain("En fazla 6 kişisel kart ekleyebilirsiniz.");
    expect(app.querySelector("#answer-text")).not.toBeNull();
  });

  it("Hazır soru yap formu kartın altında açar, Vazgeç kapatır", async () => {
    const app = await mount(<AnswerCard payload={answered} onSave={noop} isAdmin />);
    expect(app.querySelector("#ready-form")).toBeNull();

    await click(app.querySelector("#make-ready"));
    expect(app.querySelector("#ready-form")).not.toBeNull();
    expect(app.querySelector("#ready-title").value).toBe(QUESTION);
    expect(app.querySelector("#make-ready")).toBeNull();

    await click(app.querySelector("#ready-cancel"));
    expect(app.querySelector("#ready-form")).toBeNull();
    expect(app.querySelector("#make-ready")).not.toBeNull();
  });

  it("Bu SQL ile güncelle kartı bu cevapla günceller", async () => {
    api.readyUpdate.mockResolvedValue({ ready_question: { id: 14 } });
    const app = await mount(<AnswerCard payload={answered} onSave={noop} isAdmin reapproveId={14} />);

    await click(app.querySelector("#ready-reapprove"));
    await settle();

    expect(api.readyUpdate).toHaveBeenCalledWith(14, { audit_id: AUDIT, display: "table" });
    expect(app.querySelector("#ready-reapprove").textContent).toBe("Kart güncellendi");
  });

  it("yürümeyen SQL'in reddi güncelleme düğmesinin yanında okunur", async () => {
    api.readyUpdate.mockRejectedValue(new api.ApiError(422, "Bu giriş bu kolonu göremez."));
    const app = await mount(<AnswerCard payload={answered} onSave={noop} isAdmin reapproveId={14} />);

    await click(app.querySelector("#ready-reapprove"));
    await settle();

    expect(app.textContent).toContain("Bu giriş bu kolonu göremez.");
    expect(app.querySelector("#ready-reapprove").disabled).toBe(false);
  });
});
