// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import answered from "../fixtures/answered.json";
import AnswerCard from "./AnswerCard.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const noop = () => {};

// ASSUMPTION: T362'nin dört vakası düğmenin ADININ değişmesini pinliyordu; T469 o değişimi
// kusur sayıyor ve bu dosyayı adıyla istiyor, o yüzden vakalar aynı kapsamayı notun üstünden kuruyor.
let container;
let root;

// İndirme bir <a>'dır: jsdom gezinmeyi uygulamaz ve hata diye bağırır; tıklama burada yalnız
// düğmenin adına bakıldığı için gezinme engellenir — bunun için tıklamanın cancelable olması gerekir.
function render(payload) {
  container = document.createElement("div");
  document.body.append(container);
  container.addEventListener("click", (event) => {
    if (event.target.closest("a")) event.preventDefault();
  });
  root = createRoot(container);
  act(() => root.render(<AnswerCard payload={payload} onSave={noop} />));
  return container;
}

// Yeni cevap aynı kartın üstüne biner: ekran son cevabı aynı düğüme koyar, kart yeniden
// kurulmaz. Notun kapanması da bu geçişe bağlıdır.
function rerender(payload) {
  act(() => root.render(<AnswerCard payload={payload} onSave={noop} />));
}

function click(node) {
  act(() => node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })));
}

function rowsPayload(count) {
  return {
    ...answered,
    rows: Array.from({ length: count }, (_, index) => [`STK${index}`, "Ürün", index]),
    row_count: count,
    truncated: false,
  };
}

// Sayının kendi öğesi: ikilinin yanında durur, düğmelerin içine girmez.
function note(app) {
  return app.querySelector(".answer-export-note");
}

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("indirme geri bildiriminin satır sayısı", () => {
  it("Excel düğmesi indirdikten sonra da Excel'dir", () => {
    const app = render(rowsPayload(18));
    expect(app.querySelector("#export-xlsx").textContent).toBe("Excel");

    click(app.querySelector("#export-xlsx"));

    expect(app.querySelector("#export-xlsx").textContent).toBe("Excel");
    // Adını koruyan ikilinin yanında sayı tek kez okunur.
    expect(app.querySelector("#export-csv").textContent).toBe("CSV");
    expect(note(app)?.textContent).toBe("18 satır indirildi");
  });

  it("sayı ikilinin dışındaki kendi öğesinde durur", () => {
    const app = render(rowsPayload(18));
    click(app.querySelector("#export-xlsx"));

    const element = note(app);
    expect(element).not.toBeNull();
    expect(app.querySelector(".answer-export-pair").contains(element)).toBe(false);
    expect(element.textContent).toBe("18 satır indirildi");
  });

  it("kesik sonuçta sayı kartın gösterdiği satırdır, toplamın değil", () => {
    const app = render({ ...rowsPayload(50), row_count: 312, truncated: true });
    click(app.querySelector("#export-csv"));
    expect(note(app)?.textContent).toBe("50 satır indirildi");
    expect(app.querySelector("#export-csv").textContent).toBe("CSV");
  });

  it("satırı olmayan cevapta sayı uydurulmaz", () => {
    const app = render(rowsPayload(0));
    click(app.querySelector("#export-xlsx"));
    expect(note(app)?.textContent).toBe("İndirildi");
  });

  it("rows hiç yoksa da sayı uydurulmaz", () => {
    const app = render({ ...answered, rows: null });
    click(app.querySelector("#export-xlsx"));
    expect(note(app)?.textContent).toBe("İndirildi");
  });

  it("yeni cevap gelince önceki indirilenin notu kapanır", () => {
    const app = render(rowsPayload(18));
    click(app.querySelector("#export-xlsx"));
    expect(note(app)).not.toBeNull();

    rerender({ ...rowsPayload(4), audit_id: `${answered.audit_id}-2` });
    expect(note(app)).toBeNull();
  });
});
