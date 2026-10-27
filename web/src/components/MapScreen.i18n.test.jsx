// T438 (R8-20): harita ekranının dört hâli iki dilde — boş ekran, hatalı rapor, iş sürerken, iş
// bitti. İki dil aynı id kümesini boyar ve İngilizce çıktı Türkçe harf taşımaz. Verinin ve
// sunucunun cümlesi çevrilmez (küme adı, sayfa/sütun adları, denetimin satırları), o yüzden
// İngilizce geçiş İngilizce veriyle yapılıyor. Türkçe çıktı bugünkü cümleleri harfi harfine
// veriyor: MapScreen.test.jsx, MapScreenPiiTone.test.jsx ve MapScreenProgress.test.jsx o cümleleri
// bekliyor. Hata tablosu iki dilde de dört hücre kurar — satırı olmayan sorunda hücre düşerse
// mesaj geniş ekranda "Satır" başlığının altına kayıyor (M24 craft 2).
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import { I18nProvider } from "../i18n/index.js";
import * as api from "../lib/api.js";
import { initialMapState, mapReducer } from "../lib/mapFlow.js";
import MapScreen from "./MapScreen.jsx";

const TURKISH = /[çğıöşüÇĞİÖŞÜ]/;

// Kümelerin listesi iki dilde de aynı: adlar ve indeks gerekçesi veridir, kabuk çevrilir.
const DATASETS = [
  {
    name: "ornek_fatura",
    display_name: "Example invoice",
    connection: "sqlite",
    root: "datasets",
    active: true,
    index: { exists: true, fresh: true, reason: null },
  },
  {
    name: "synthetic_erp",
    display_name: "Synthetic ERP",
    connection: "sqlite",
    root: "datasets",
    active: false,
    index: { exists: false, fresh: false, reason: "No index has been built." },
  },
];

function render(element) {
  return renderToStaticMarkup(element)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&");
}

const inLang = (lang, element) => render(<I18nProvider lang={lang}>{element}</I18nProvider>);
const ids = (html) => [...html.matchAll(/id="([^"]+)"/g)].map((match) => match[1]).sort();
const run = (actions, state = initialMapState) =>
  actions.reduce((current, action) => mapReducer(current, action), state);

// Sözleşme "preview response"un iki dildeki örneği: hata ve uyarı satırları sunucudan gelir.
function preview(lang, overrides = {}) {
  return {
    preview_id: "p-1",
    dataset: {
      name: "ornek_fatura",
      display_name: lang === "en" ? "Example invoice" : "Örnek Fatura",
      connection: "sqlite",
    },
    counts: { tables: 3, columns: 24, pii: 2, deny: 1, references: 5, rules: 4 },
    errors: [],
    warnings: [],
    db_check: { checked: false, missing_in_db: [], only_in_db: [], message: null },
    ...overrides,
  };
}

const ERRORS = {
  tr: [
    { sheet: "Kolonlar", row: 7, column: "TABLO", message: "Tablo şablonda yok: Satis.Cari." },
    { sheet: "Veri kümesi", row: null, column: null, message: "Bu ad zaten bir veri kümesi: ornek_fatura." },
  ],
  en: [
    { sheet: "Columns", row: 7, column: "TABLE", message: "The table is not in the template: Satis.Cari." },
    { sheet: "Dataset", row: null, column: null, message: "This name is already a dataset: ornek_fatura." },
  ],
};

// Yirmisi yazılır, kalanı tek cümleyle sayılır.
const warnings = (lang) =>
  Array.from({ length: 25 }, (_, index) => ({
    sheet: lang === "en" ? "Columns" : "Kolonlar",
    row: index + 2,
    column: lang === "en" ? "DESCRIPTION" : "AÇIKLAMA",
    message: lang === "en" ? `warning ${index + 1}` : `uyarı ${index + 1}`,
  }));

const job = (phase, message = null) => ({ preview_id: "p-1", name: "ornek_fatura", phase, message });

// Haller gerçek geçişlerden indirgeniyor: ekranın ne yazdığı akışın nerede durduğundan okunuyor.
function states(lang) {
  const loaded = (overrides) => [
    { type: "select", filename: "harita.xlsx" },
    { type: "preview" },
    { type: "previewed", preview: preview(lang, overrides) },
  ];
  // Kurulan küme SQL Server'a bakıyorsa geçme düğmesinin yanı bağlantı bağlantısını da alıyor.
  const mssql = {
    dataset: {
      name: "ornek_fatura",
      display_name: lang === "en" ? "Example invoice" : "Örnek Fatura",
      connection: "mssql",
    },
  };
  return {
    blank: run([]),
    errors: run(loaded({ errors: ERRORS[lang], warnings: warnings(lang) })),
    progress: run([...loaded(), { type: "apply" }, { type: "job", job: job("writing") }]),
    done: run([...loaded(mssql), { type: "apply" }, { type: "job", job: job("indexing") }, { type: "job", job: job("done") }]),
  };
}

const NAMES = ["blank", "errors", "progress", "done"];

const props = (lang, name) => ({
  state: states(lang)[name],
  info: { db_connection: true },
  datasets: DATASETS,
  active: "ornek_fatura",
});
const screen = (lang, name) => inLang(lang, <MapScreen {...props(lang, name)} />);

afterEach(() => {
  api.setApiLang(null);
});

describe("harita ekranı iki dilde", () => {
  it("dört hâli de aynı id kümesini boyuyor: çeviri markup'ı değiştirmez", () => {
    for (const name of NAMES) {
      const tr = ids(screen("tr", name));
      expect(tr).toContain("map-screen");
      expect(ids(screen("en", name))).toEqual(tr);
    }
  });

  it("İngilizce ekran Türkçe harf ve bugünün cümlesini taşımıyor", () => {
    const blank = screen("en", "blank");
    expect(blank).not.toMatch(TURKISH);
    for (const text of [
      ">New database</h1>",
      " · Get the template</h2>",
      " · Check the file you filled in</h2>",
      " · Datasets</h2>",
      ">Download</span>",
      ">Fill in</span>",
      ">Upload</span>",
      ">Download the empty template</a>",
      ">Fill it from the live database</button>",
      ">Try the filled-in example</button>",
      ">Template file (.xlsx)</label>",
      ">Choose a template…</label>",
      ">Check it</button>",
      "Choose the template you filled in first.",
    ]) {
      expect(blank).toContain(text);
    }
    for (const text of [">Yeni veritabanı<", ">Boş şablonu indir<", ">Kontrol et</button>", ">Önce doldurduğunuz"]) {
      expect(blank).not.toContain(text);
    }

    const errors = screen("en", "errors");
    expect(errors).not.toMatch(TURKISH);
    for (const text of [">Sheet</th>", ">Row</th>", ">Column</th>", ">Problem</th>", ">Tables</dt>", ">Personal data</dt>"]) {
      expect(errors).toContain(text);
    }
    expect(errors).toContain("and 5 more");
    expect(errors).toContain("Fix the errors first.");
    expect(errors).toContain("There is no live database connection; nothing was compared.");
    expect(errors).toContain("The table is not in the template: Satis.Cari.");

    expect(screen("en", "progress")).toContain("●</span>Writing</li>");
    expect(screen("en", "progress")).toContain("○</span>Building the index</li>");
    const done = screen("en", "done");
    expect(done).toContain("✓</span>Ready</li>");
    expect(done).toContain(">Switch to this dataset</button>");
    expect(done).toContain(">Enter the connection now</a>");
  });

  it("Türkçe ekran bugünkü cümleleri harfi harfine veriyor ve provider'sız haliyle aynı", () => {
    for (const name of NAMES) {
      expect(render(<MapScreen {...props("tr", name)} />)).toBe(screen("tr", name));
    }

    const blank = screen("tr", "blank");
    for (const text of [
      ">Yeni veritabanı</h1>",
      " · Şablonu alın</h2>",
      " · Doldurduğunuz dosyayı denetleyin</h2>",
      " · Veri kümeleri</h2>",
      ">İndir</span>",
      ">Doldur</span>",
      ">Yükle</span>",
      ">Boş şablonu indir</a>",
      ">Canlı veritabanından doldur</button>",
      ">Örnek dolu şablonla dene</button>",
      ">Kontrol et</button>",
      "Önce doldurduğunuz şablonu seçin.",
    ]) {
      expect(blank).toContain(text);
    }

    const errors = screen("tr", "errors");
    for (const text of [">Sayfa</th>", ">Satır</th>", ">Kolon</th>", ">Sorun</th>", ">Tablo</dt>", ">Kişisel veri</dt>"]) {
      expect(errors).toContain(text);
    }
    expect(errors).toContain("ve 5 tane daha");
    expect(errors).toContain("Önce hataları düzeltin.");
    expect(errors).toContain(">Oluştur</button>");
    expect(errors).toContain("Canlı veritabanı bağlantısı yok; karşılaştırma yapılmadı.");
    expect(errors).toContain("Kapalı: modelin hiçbir metnine düşmeyen kolonlar");

    expect(screen("tr", "progress")).toContain("●</span>Yazılıyor</li>");
    expect(screen("tr", "progress")).toContain("○</span>İndeks kuruluyor</li>");
    const done = screen("tr", "done");
    expect(done).toContain("✓</span>Hazır</li>");
    expect(done).toContain(">Bu veri kümesine geç</button>");
    expect(done).toContain(">Şimdi bağlantıyı girin</a>");
  });

  it("hata tablosu iki dilde de dört hücre kuruyor, boş hücresi — okunuyor", () => {
    for (const lang of ["tr", "en"]) {
      const html = screen(lang, "errors");
      expect(html.match(/<td/g)).toHaveLength(8); // iki satır × dört hücre
      expect(html).toContain(">—</td>");
      expect(html).toContain('class="map-cell-blank"');
    }
  });

  it("şablonun adresi arayüz dilini sorgu parametresi olarak taşıyor", () => {
    api.setApiLang("en");
    expect(screen("en", "blank")).toContain('id="map-template" href="/api/schema-map/template.xlsx?lang=en"');
    api.setApiLang("tr");
    expect(screen("tr", "blank")).toContain('id="map-template" href="/api/schema-map/template.xlsx?lang=tr"');
  });
});
