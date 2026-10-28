// M28 craft 2: adım bandı yalnız 1. kartı yakıyordu — dosya denetlenip küme kurulduğu hâlde 2 ve 3
// numarasında kalıyor, bant süs gibi okunuyordu. İşaret artık her kartın kendi işinin sonucundan
// okunur: rapor hatasız döndü (2), kurulan küme kümeler listesinde göründü (3).
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import MapScreen from "./MapScreen.jsx";
import { initialMapState, mapReducer } from "../lib/mapFlow.js";

function render(element) {
  return renderToStaticMarkup(element)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&");
}

// Haller gerçek geçişlerden indirgeniyor: kartın hâli akışın nerede durduğundan okunuyor.
function run(actions) {
  return actions.reduce((current, action) => mapReducer(current, action), initialMapState);
}

function previewResponse(overrides = {}) {
  return {
    preview_id: "p-1",
    dataset: { name: "ornek_fatura", display_name: "Örnek Fatura", connection: "sqlite" },
    counts: { tables: 3, columns: 24, pii: 0, deny: 0, references: 5, rules: 4 },
    errors: [],
    warnings: [],
    db_check: { checked: false, missing_in_db: [], only_in_db: [], message: null },
    ...overrides,
  };
}

const job = (phase, message = null) => ({ preview_id: "p-1", name: "ornek_fatura", phase, message });

const FILE = [{ type: "select", filename: "harita.xlsx" }, { type: "preview" }];
const REPORTED = [...FILE, { type: "previewed", preview: previewResponse() }];
const CREATED = [...REPORTED, { type: "apply" }, { type: "job", job: job("done") }];

const LISTED = {
  name: "ornek_fatura",
  display_name: "Örnek Fatura",
  connection: "sqlite",
  active: false,
  index: { exists: true, fresh: true, reason: null },
};

const TITLES = ["Şablonu alın</h2>", "denetleyin</h2>", "Veri kümeleri</h2>"];

// Kartın kendi açılış div'i: başlığın gerisindeki en yakın div, o kartın div'idir.
function cardTag(html, heading) {
  const at = html.indexOf(heading);
  const open = html.lastIndexOf("<div", at);
  return html.slice(open, html.indexOf(">", open));
}

function states(html) {
  return TITLES.map((heading) => cardTag(html, heading).match(/data-step-state="(\w+)"/)?.[1] ?? "");
}

// Numaranın yazıldığı işaret: biten kartta tik, diğerlerinde kartın numarası.
function marks(html) {
  return TITLES.map((heading) => {
    const open = html.lastIndexOf('<span class="map-card-n"', html.indexOf(heading));
    const start = html.indexOf(">", open) + 1;
    return html.slice(start, html.indexOf("</span>", start));
  });
}

const screen = (state, props = {}) => render(<MapScreen state={state} {...props} />);

describe("harita sihirbazı — adımların işareti", () => {
  it("boş ekranda üç kart da numarasını taşır", () => {
    const html = screen(run([]));
    expect(marks(html)).toEqual(["1", "2", "3"]);
    expect(states(html)).toEqual(["current", "todo", "todo"]);
  });

  it("hatayla dönen önizlemede 2 numarasını korur", () => {
    const failed = previewResponse({ errors: [{ sheet: "Tablolar", row: 3, column: null, message: "Kolon adı boş." }] });
    const html = screen(run([...FILE, { type: "previewed", preview: failed }]));
    expect(marks(html)).toEqual(["✓", "2", "3"]);
    expect(states(html)).toEqual(["done", "current", "todo"]);
  });

  it("hatasız önizleme 2'i bitirir, sıra kümeler kartına geçer", () => {
    const html = screen(run(REPORTED));
    expect(marks(html)).toEqual(["✓", "✓", "3"]);
    expect(states(html)).toEqual(["done", "done", "current"]);
  });

  it("iş bitti ama küme listede yoksa 3 numarasını korur", () => {
    const html = screen(run(CREATED), { datasets: [] });
    expect(marks(html)).toEqual(["✓", "✓", "3"]);
    expect(states(html)[2]).toBe("current");
  });

  it("kurulan küme listeye düşünce 3 de biter", () => {
    const html = screen(run(CREATED), { datasets: [LISTED] });
    expect(marks(html)).toEqual(["✓", "✓", "✓"]);
    expect(states(html)).toEqual(["done", "done", "done"]);
  });

  it("geçiş tamamlandığında üç kart bitmiş kalır", () => {
    const html = screen(run([...CREATED, { type: "activated", name: "ornek_fatura" }]), {
      datasets: [LISTED],
      active: "ornek_fatura",
    });
    expect(marks(html)).toEqual(["✓", "✓", "✓"]);
  });

  it("önizlemenin adıyla aynı ada sahip eski bir küme 3'ü yakmaz", () => {
    const html = screen(run(REPORTED), { datasets: [LISTED] });
    expect(marks(html)[2]).toBe("3");
    expect(states(html)[2]).toBe("current");
  });
});
