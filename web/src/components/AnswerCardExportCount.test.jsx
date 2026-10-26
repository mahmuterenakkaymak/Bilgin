// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import answered from "../fixtures/answered.json";
import AnswerCard from "./AnswerCard.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const noop = () => {};

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

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("indirme geri bildiriminin satır sayısı", () => {
  it("Excel düğmesi indirdiği satır sayısını adında taşır", () => {
    const app = render(rowsPayload(18));
    expect(app.querySelector("#export-xlsx").textContent).toBe("Excel");

    click(app.querySelector("#export-xlsx"));

    expect(app.querySelector("#export-xlsx").textContent).toBe("18 satır indirildi");
    // Sayı bir kez okunur: basılmayan düğme kendi adında kalır.
    expect(app.querySelector("#export-csv").textContent).toBe("CSV");
  });

  it("kesik sonuçta sayı kartın gösterdiği satırdır, toplamın değil", () => {
    const app = render({ ...rowsPayload(50), row_count: 312, truncated: true });
    click(app.querySelector("#export-csv"));
    expect(app.querySelector("#export-csv").textContent).toBe("50 satır indirildi");
  });

  it("satırı olmayan cevapta ad bugünkü İndirildi'dir", () => {
    const app = render(rowsPayload(0));
    click(app.querySelector("#export-xlsx"));
    expect(app.querySelector("#export-xlsx").textContent).toBe("İndirildi");
  });

  it("rows hiç yoksa da sayı uydurulmaz", () => {
    const app = render({ ...answered, rows: null });
    click(app.querySelector("#export-xlsx"));
    expect(app.querySelector("#export-xlsx").textContent).toBe("İndirildi");
  });
});
