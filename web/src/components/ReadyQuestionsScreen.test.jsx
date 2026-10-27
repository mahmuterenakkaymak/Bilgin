// @vitest-environment jsdom
// Defter hem işaret hem olay ister: grupların kurulması ve düğmelerin kimin için var olduğu SSR
// ile okunur, tıklamalar, girdiği ve reddin cümlesi jsdom'da koşar. Satırlar sözleşme "ready
// question" alanlarıdır — `sql` yalnız sunucuda kalır, ekrana hiçbir yerde düşmez.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App.jsx";
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

const ID = "3f2a9c0d1e4b4a7f8c6d5e2b1a0f9e8d";
const NOT_ALLOWED = "Bu sayfa yalnız yöneticiye açık.";
const ADMIN = { username: "admin", role: "admin" };
const USER = { username: "analist", role: "user" };
const JOB_POLL_MS = 2000;

function ready(over) {
  return {
    id: 1,
    dataset: "wwi",
    business_role: "satis",
    title: "Bu ay net satış",
    question: "Bu ay net satışımız ne kadar?",
    sql: "SELECT SUM(TUTAR) FROM VFILINE",
    display: "number",
    position: 1,
    created_by: "admin",
    approved: true,
    audit_id: "a1",
    created_at: "2026-10-25T09:00:00+00:00",
    ...over,
  };
}

const SATIS = ready();
const SATIS_DRAFT = ready({ id: 2, title: "Günlük ziyaret sayısı", display: "table", position: 0, approved: false });
const COMMON_DRAFT = ready({ id: 3, business_role: "*", title: "Ay ay ciro", display: "chart", position: 2, approved: false });
const PERSONAL = ready({ id: 4, business_role: null, title: "Cari bakiyesi", created_by: "analist" });
const ROWS = [SATIS, SATIS_DRAFT, COMMON_DRAFT, PERSONAL];

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

async function mount(props = {}) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => {
    root.render(<ReadyQuestionsScreen rows={ROWS} {...props} />);
  });
  return container;
}

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

// Sahte zaman kurulan testte `settle`'ın beklemesi gereken bir saat yoktur: zincirli
// promise'ların sırası mikro görevlerle döner (MapScreen.test.jsx'in düzeni).
async function flush() {
  await act(async () => {
    for (let turn = 0; turn < 10; turn += 1) await Promise.resolve();
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

beforeEach(() => {
  window.location.hash = "#/";
});

afterEach(() => {
  if (root) {
    act(() => root.unmount());
    root = undefined;
  }
  container?.remove();
  container = undefined;
  window.location.hash = "#/";
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("ReadyQuestionsScreen yapısı", () => {
  it("gruplar rol sırasıyla kurulur: Satış, Herkes, Kişisel", () => {
    const html = render(<ReadyQuestionsScreen rows={ROWS} />);
    expect(Array.from(html.matchAll(/data-ready-group="([^"]*)"/g), (match) => match[1])).toEqual([
      "satis",
      "*",
      "personal",
    ]);
    expect(html).toContain(">Satış</h2>");
    expect(html).toContain(">Herkes</h2>");
    expect(html).toContain(">Kişisel</h2>");
  });

  it("onay bekleyen satır rozet ve Onayla düğmesi taşır; onaylı satır taşımaz", () => {
    const html = render(<ReadyQuestionsScreen rows={ROWS} />);
    expect(html.match(/Onay bekliyor/g)).toHaveLength(2);
    expect(html).toContain('data-ready-approve="2"');
    expect(html).toContain('data-ready-approve="3"');
    expect(html).not.toContain('data-ready-approve="1"');
  });

  it("her satırın aç, düzenle ve sil düğmeleri kendi kimliğiyle durur; SQL hiçbir yerde okunmaz", () => {
    const html = render(<ReadyQuestionsScreen rows={ROWS} />);
    for (const id of [1, 2, 3, 4]) {
      expect(html).toContain(`data-ready-open="${id}"`);
      expect(html).toContain(`data-ready-edit="${id}"`);
      expect(html).toContain(`data-ready-delete="${id}"`);
    }
    expect(html).toContain(">Bu ay net satışımız ne kadar?</p>");
    expect(html).toContain("Tek sayı · sıra 1 · admin");
    expect(html).not.toContain("SELECT");
    expect(html).not.toContain("VFILINE");
    expect(html).not.toContain("undefined");
  });

  it("liste boşken tek cümle, okunurken ayrı cümle, okuma hatasında bant", () => {
    const empty = render(<ReadyQuestionsScreen rows={[]} />);
    expect(empty).toContain("Henüz hazır soru yok");
    expect(render(<ReadyQuestionsScreen rows={[]} loading />)).toContain("Hazır sorular okunuyor…");

    const broken = render(<ReadyQuestionsScreen rows={[]} error="Hazır sorular okunamadı." />);
    expect(broken).toContain('id="ready-read-error"');
    expect(broken).toContain("Hazır sorular okunamadı.");
    expect(broken).not.toContain("Henüz hazır soru yok");
  });
});

describe("ReadyQuestionsScreen olayları", () => {
  it("Onayla satırı onaylar, listeyi baştan okur ve yaptığını söyler", async () => {
    api.readyUpdate.mockResolvedValue({ ready_question: { ...SATIS_DRAFT, approved: true } });
    const refreshed = [];
    const app = await mount({ onRefresh: () => refreshed.push(1) });

    await click(app.querySelector('button[data-ready-approve="2"]'));
    await settle();

    expect(api.readyUpdate).toHaveBeenCalledWith(2, { approved: true });
    expect(refreshed).toEqual([1]);
    expect(app.querySelector("#ready-note").textContent).toContain("Günlük ziyaret sayısı” onaylandı");
  });

  it("Düzenle alanları satırın değerleriyle açar; Kaydet başlık, rol, görünüm ve sırayı gönderir", async () => {
    api.readyUpdate.mockResolvedValue({ ready_question: SATIS });
    const refreshed = [];
    const app = await mount({ onRefresh: () => refreshed.push(1) });

    await click(app.querySelector('button[data-ready-edit="1"]'));
    expect(app.querySelector("#ready-edit-title").value).toBe("Bu ay net satış");
    expect(app.querySelector("#ready-edit-role").value).toBe("satis");
    expect(app.querySelector("#ready-edit-display").value).toBe("number");
    expect(app.querySelector("#ready-edit-position").value).toBe("1");

    await fill(app.querySelector("#ready-edit-title"), "Net satış (aylık)");
    await fill(app.querySelector("#ready-edit-role"), "yonetim");
    await fill(app.querySelector("#ready-edit-position"), "4");
    await click(app.querySelector("#ready-edit-save"));
    await settle();

    expect(api.readyUpdate).toHaveBeenCalledWith(1, {
      title: "Net satış (aylık)",
      display: "number",
      business_role: "yonetim",
      position: 4,
    });
    expect(refreshed).toEqual([1]);
    expect(app.querySelector("#ready-edit-title")).toBeNull();
  });

  it("reddedilen kayıt formu açık bırakır ve cümlesi bantta okunur", async () => {
    api.readyUpdate.mockRejectedValue(new api.ApiError(422, "Geçersiz görünüm: number, chart ya da table olmalı."));
    const app = await mount();

    await click(app.querySelector('button[data-ready-edit="1"]'));
    await click(app.querySelector("#ready-edit-save"));
    await settle();

    expect(app.querySelector("#ready-edit-title")).not.toBeNull();
    expect(app.querySelector("#ready-error").textContent).toContain("Geçersiz görünüm");
  });

  it("boş başlık kaydedilmez, nedeni söylenir", async () => {
    const app = await mount();

    await click(app.querySelector('button[data-ready-edit="1"]'));
    await fill(app.querySelector("#ready-edit-title"), "   ");
    await click(app.querySelector("#ready-edit-save"));
    await settle();

    expect(api.readyUpdate).not.toHaveBeenCalled();
    expect(app.querySelector("#ready-error").textContent).toContain("Başlık boş olamaz.");
  });

  it("Sil iki adımlıdır: onay gelmeden hiçbir istek gitmez", async () => {
    api.readyRemove.mockResolvedValue({ deleted: 1 });
    const refreshed = [];
    const app = await mount({ onRefresh: () => refreshed.push(1) });

    await click(app.querySelector('button[data-ready-delete="1"]'));
    expect(api.readyRemove).not.toHaveBeenCalled();
    expect(app.textContent).toContain("Silinsin mi?");

    await click(app.querySelector('[data-ready-delete-confirm="1"]'));
    await settle();

    expect(api.readyRemove).toHaveBeenCalledWith(1);
    expect(refreshed).toEqual([1]);
    expect(app.querySelector("#ready-note").textContent).toContain("Bu ay net satış” silindi.");
  });

  it("Aç cevabı yeni bir konuşmada açar", async () => {
    api.startOpen.mockResolvedValue({ conversation_id: ID });
    const app = await mount();

    await click(app.querySelector('button[data-ready-open="1"]'));
    await settle();

    expect(api.startOpen).toHaveBeenCalledWith(1);
    expect(window.location.hash).toBe(`#/c/${ID}`);
  });

  it("onaysız satırın ön izlemesi yürümezse cümle satırın ekranında kalır, adres değişmez", async () => {
    api.startOpen.mockRejectedValue(new api.ApiError(404, "Hazır soru bulunamadı."));
    const app = await mount();

    await click(app.querySelector('button[data-ready-open="2"]'));
    await settle();

    expect(app.querySelector("#ready-error").textContent).toContain("Hazır soru bulunamadı.");
    expect(window.location.hash).toBe("#/");
  });

  it("Öneri iste işi başlatır, aşama satırı koşarken güncellenir ve bitince liste baştan okunur", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    api.readySuggest.mockResolvedValue({ job_id: "j1", phase: "asking", asked: 0, stored: 0, message: null });
    api.readySuggestStatus.mockResolvedValue({ job_id: "j1", phase: "done", asked: 12, stored: 9, message: null });
    const refreshed = [];
    const app = await mount({ onRefresh: () => refreshed.push(1) });

    await click(app.querySelector("#ready-suggest"));
    await flush();

    expect(api.readySuggest).toHaveBeenCalledTimes(1);
    expect(app.querySelector("#ready-job").textContent).toBe("Öneri koşuyor: 0 soru soruldu, 0 aday eklendi.");
    expect(app.querySelector("#ready-suggest").disabled).toBe(true);

    await act(async () => {
      vi.advanceTimersByTime(JOB_POLL_MS);
    });
    await flush();

    expect(api.readySuggestStatus).toHaveBeenCalledWith("j1");
    expect(app.querySelector("#ready-job").textContent).toBe("Öneri bitti: 12 soru soruldu, 9 aday onay bekliyor.");
    expect(app.querySelector("#ready-suggest").disabled).toBe(false);
    expect(refreshed).toEqual([1]);
  });

  it("işin reddi cümlesiyle okunur, aday satırlar uydurulmaz", async () => {
    api.readySuggest.mockRejectedValue(new api.ApiError(404, "Hazır soru bulunamadı."));
    const app = await mount();

    await click(app.querySelector("#ready-suggest"));
    await settle();

    expect(app.querySelector("#ready-error").textContent).toContain("Hazır soru bulunamadı.");
    expect(app.querySelector("#ready-job")).toBeNull();
  });
});

describe("Satırın başlığı ile sorusu", () => {
  // Satırın kendi ekranı: grup başlıkları ile not bantları saymaya karışmasın.
  function rowHtml(row) {
    const html = render(<ReadyQuestionsScreen rows={[row]} />);
    return html.match(/<li class="card ready-row"[\s\S]*?<\/li>/)[0];
  }

  it("başlığı olmayan ya da başlığı sorusunun kendisi olan satır soruyu bir kez basar", () => {
    const question = "Geçen ay net satışımız ne kadardı?";

    const drafts = rowHtml(ready({ id: 7, title: question, question, approved: false }));
    expect(drafts.split(question)).toHaveLength(2);
    expect(drafts).not.toContain('class="ready-row-question"');
    expect(drafts).toContain("Onay bekliyor");

    const untitled = rowHtml(ready({ id: 8, title: "", question, approved: false }));
    expect(untitled.split(question)).toHaveLength(2);
    expect(untitled).toContain('class="ready-row-question"');
  });

  it("gerçek başlıklı satır başlığı ile soruyu iki ayrı satırda korur", () => {
    const question = "Geçen ay net satışımız ne kadardı?";
    const row = rowHtml(ready({ id: 9, title: "Ciro", question }));

    expect(row).toContain("Ciro");
    expect(row.split(question)).toHaveLength(2);
    expect(row).toContain(`>${question}</p>`);
  });
});

describe("Rol kapısı", () => {
  it("sıradan kullanıcı #/hazir-sorular ile açınca defter boyanmaz, gezinmede bağlantı yoktur", () => {
    window.location.hash = "#/hazir-sorular";
    const html = render(<App user={USER} />);
    expect(html).not.toContain('id="ready-screen"');
    expect(html).not.toContain('id="nav-ready"');
    expect(html).toContain('id="route-note"');
    expect(html).toContain(NOT_ALLOWED);
  });

  it("yönetici #/hazir-sorular ile açınca defteri görür, uyarı düşmez", () => {
    window.location.hash = "#/hazir-sorular";
    const html = render(<App user={ADMIN} />);
    expect(html).toContain('id="ready-screen"');
    expect(html).toContain('id="nav-ready"');
    expect(html).toContain("Hazır sorular okunuyor…");
    expect(html).not.toContain('id="route-note"');
  });
});
