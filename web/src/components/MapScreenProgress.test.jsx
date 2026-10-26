// Üç kart hep açık ve hep aynı hâlde kalıyordu: "Oluştur" başarılı olduktan sonra
// "1 · Şablonu alın" dosya seçilmeden önce tam olarak nasıl görünüyorsa öyle görünüyordu.
// Kart artık kendi numarasının üstünde ne kadar ilerlediğini söylüyor: data-step-state ve
// bitende tik. Hâl ekranın zaten tuttuğundan okunur — şablon, rapor, kurulan küme.
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

const REPORT = {
  preview_id: "p-1",
  dataset: { name: "ornek_fatura", display_name: "Örnek Fatura", connection: "sqlite" },
  counts: { tables: 3, columns: 24, pii: 0, deny: 0, references: 5, rules: 4 },
  errors: [],
  warnings: [],
  db_check: { checked: false, missing_in_db: [], only_in_db: [], message: null },
};

const job = (phase, message = null) => ({ preview_id: "p-1", name: "ornek_fatura", phase, message });

const FILE = [{ type: "select", filename: "harita.xlsx" }, { type: "preview" }];
const REPORTED = [...FILE, { type: "previewed", preview: REPORT }];
const CREATED = [...REPORTED, { type: "apply" }, { type: "job", job: job("done") }];

// Kartın kendi açılış div'i: başlığın gerisindeki en yakın div, o kartın div'idir.
function cardTag(html, heading) {
  const at = html.indexOf(heading);
  const open = html.lastIndexOf("<div", at);
  return html.slice(open, html.indexOf(">", open));
}

const TITLES = ["Şablonu alın</h2>", "denetleyin</h2>", "Veri kümeleri</h2>"];

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

const screen = (state) => render(<MapScreen state={state} />);

describe("harita sihirbazı — adımların hâli", () => {
  it("boş ekranda 1 sürer, 2 ve 3 sırasını bekler", () => {
    const html = screen(run([]));
    expect(states(html)).toEqual(["current", "todo", "todo"]);
    expect(marks(html)).toEqual(["1", "2", "3"]);
  });

  it("rapor gelince 1 biter ve 2 sürer, 3 beklemeye devam eder", () => {
    const html = screen(run(REPORTED));
    expect(states(html)).toEqual(["done", "current", "todo"]);
    expect(marks(html)).toEqual(["✓", "2", "3"]);
  });

  it("küme kurulunca 1 ve 2 biter, sıra 3'e geçer", () => {
    const html = screen(run(CREATED));
    expect(states(html)).toEqual(["done", "done", "current"]);
    expect(marks(html)).toEqual(["✓", "✓", "3"]);
  });

  it("geçiş de tamamlanınca üç kart biter", () => {
    const html = screen(run([...CREATED, { type: "activated", name: "ornek_fatura" }]));
    expect(states(html)).toEqual(["done", "done", "done"]);
  });
});
