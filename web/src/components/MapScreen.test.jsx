// Ekran SSR ile kuruluyor: indirgeyicinin her hali sunucuya çıkmadan işaretine bakılarak
// okunur. Ağın kendisi (yükleme, küme kurma, geçiş) sunucu tarafında tests/test_web_map_api.py
// ve tests/test_web_datasets_api.py'de koşuluyor; burada yalnız o cevabın ekranda ne yazdığı var.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import App from "../App.jsx";
import { initialMapState, mapReducer } from "../lib/mapFlow.js";
import MapScreen, { MapFlow } from "./MapScreen.jsx";

function render(element) {
  return renderToStaticMarkup(element)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&");
}

const screen = (props) => render(<MapScreen {...props} />);

// Haller gerçek geçişlerden kuruluyor: ekranın ne yazdığı, akışın nerede durduğundan okunuyor.
function run(actions, state = initialMapState) {
  return actions.reduce((current, action) => mapReducer(current, action), state);
}

const LOADED = [
  { type: "select", filename: "harita.xlsx" },
  { type: "preview" },
  { type: "previewed", preview: previewResponse() },
];

// Sözleşme "preview response"un gerçekçi örneği.
function previewResponse(overrides = {}) {
  return {
    preview_id: "p-1",
    dataset: { name: "ornek_fatura", display_name: "Örnek Fatura", connection: "sqlite" },
    counts: { tables: 3, columns: 24, pii: 2, deny: 1, references: 5, rules: 4 },
    errors: [],
    warnings: [],
    db_check: {
      checked: false,
      missing_in_db: [],
      only_in_db: [],
      message: "Canlı veritabanı bağlantısı yok; karşılaştırma yapılmadı.",
    },
    ...overrides,
  };
}

const job = (phase, message = null) => ({ preview_id: "p-1", name: "ornek_fatura", phase, message });

const DATASETS = [
  {
    name: "ornek_fatura",
    display_name: "Örnek Fatura",
    connection: "sqlite",
    root: "real_datasets",
    active: true,
    index: { exists: true, fresh: true, reason: null },
  },
  {
    name: "synthetic_erp",
    display_name: "Sentetik ERP",
    connection: "sqlite",
    root: "datasets",
    active: false,
    index: { exists: true, fresh: false, reason: "Kurallar değişti." },
  },
  {
    name: "wwi_real",
    display_name: "WWI Gerçek",
    connection: "mssql",
    root: "real_datasets",
    active: false,
    index: { exists: false, fresh: false, reason: "İndeks hiç kurulmamış." },
  },
];

// Satır kendi küme adından bulunur: sıra değişse de ölçüm satıra bakar.
function row(html, name) {
  return html.split('<li class="dataset-row"').slice(1).find((chunk) => chunk.includes(`>${name}<`)) ?? "";
}

// Düğmenin kendi etiketi: `disabled` var mı, hangi sözcüğü söylüyor.
function tag(html, id) {
  const open = html.indexOf(`id="${id}"`);
  return html.slice(html.lastIndexOf("<", open), html.indexOf(">", open));
}

describe("MapScreen — şablon kartı", () => {
  it("boş ekran üç adımı ve indirme yollarını kurar", () => {
    const html = screen({});
    expect(html).toContain('id="map-screen"');
    expect(html).toContain(">Yeni veritabanı</h1>");
    for (const step of ["İndir", "Doldur", "Yükle"]) {
      expect(html).toContain(`>${step}</span>`);
    }
    expect(html).toContain('id="map-template"');
    expect(html).toContain('href="/api/schema-map/template.xlsx"');
    expect(html).toContain(">Örnek dolu şablonla dene</button>");
    expect(html).toContain('id="map-file"');
    expect(html).toContain('id="map-preview"');
  });

  it("canlı veritabanı düğmesi yalnız info.db_connection doğruysa kurulur", () => {
    expect(screen({ info: { db_connection: true } })).toContain('id="map-template-db"');
    for (const info of [null, { db_connection: false }]) {
      expect(screen({ info })).not.toContain("map-template-db");
    }
  });

  it("yoklamanın duyurusu indirmenin altında kendi bandında durur", () => {
    const note = { tone: "warn", text: "Salt okunur giriş tablo bilgisini okuyamadı; boş şablon verildi." };
    const html = screen({ info: { db_connection: true }, note });
    expect(html).toContain('id="map-note"');
    expect(html).toContain("boş şablon verildi.");
    expect(html).toContain('class="map-note"');
    expect(screen({ note: { tone: "error", text: "Şablon indirilemedi." } })).toContain('class="map-note is-error"');
  });
});

describe("MapScreen — denetim raporu", () => {
  it("dosya seçilmeden kontrol sunucuya gitmez, cümlesiyle bekler", () => {
    const html = screen({ state: run([{ type: "preview" }]) });
    expect(html).toContain('id="map-hint"');
    expect(html).toContain("Önce doldurduğunuz şablonu seçin.");
    expect(html).toContain('class="map-hint is-alert"');
    expect(html).not.toContain('id="map-report"');
    expect(html).not.toContain('id="map-apply"');
    // dosya seçilmeden önce aynı cümle sessiz ipucu olarak duruyor
    const idle = screen({});
    expect(idle).toContain("Önce doldurduğunuz şablonu seçin.");
    expect(idle).toContain('class="map-hint"');
  });

  it("kontrol sürerken düğme kendi sözcüğünü söyler", () => {
    const html = screen({ state: run([{ type: "select", filename: "h.xlsx" }, { type: "preview" }]) });
    expect(html).toContain(">Kontrol ediliyor…</button>");
    expect(tag(html, "map-preview")).toContain("disabled");
  });

  it("hatalı rapor sayıları, hata satırları ve kapalı Oluştur'u gerekçesiyle gösterir", () => {
    const state = run([
      LOADED[0],
      LOADED[1],
      {
        type: "previewed",
        preview: previewResponse({
          errors: [
            { sheet: "Kolonlar", row: 7, column: "TABLO", message: "Tablo şablonda yok: Satis.Cari." },
            { sheet: "Veri kümesi", row: null, column: "AD", message: "Bu ad zaten bir veri kümesi: ornek_fatura." },
          ],
          warnings: Array.from({ length: 41 }, (_, index) => ({
            sheet: "Kolonlar",
            row: index + 2,
            column: "AÇIKLAMA",
            message: `uyarı ${index + 1}`,
          })),
        }),
      },
    ]);
    const html = screen({ state });
    expect(html).toContain('id="map-report"');
    for (const label of ["Tablo", "Kolon", "Kişisel veri", "Kapalı", "Referans", "Kural"]) {
      expect(html).toContain(`>${label}</dt>`);
    }
    expect(html).toContain(">3</dd>");
    expect(html).toContain("Küme olacak:");
    expect(html).toContain('id="map-errors"');
    for (const column of ["Sayfa", "Satır", "Kolon", "Sorun"]) {
      expect(html).toContain(`>${column}</th>`);
    }
    expect(html).toContain("Tablo şablonda yok: Satis.Cari.");
    expect(html).toContain(">7</td>");
    expect(html).toContain(">—</td>"); // satırı olmayan hata
    expect(tag(html, "map-apply")).toContain("disabled");
    expect(html).toContain("Önce hataları düzeltin.");
    // uyarılardan yirmisi yazılır, kalanı tek cümleyle sayılır
    expect(html).toContain("uyarı 20");
    expect(html).not.toContain("uyarı 21");
    expect(html).toContain("ve 21 tane daha");
    expect(html).toContain("Canlı veritabanı bağlantısı yok; karşılaştırma yapılmadı.");
  });

  it("temiz raporda Oluştur açıktır, uyarı bandı kurulmaz", () => {
    const html = screen({ state: run(LOADED) });
    expect(tag(html, "map-apply")).not.toContain("disabled");
    expect(html).toContain(">Oluştur</button>");
    expect(html).not.toContain("Önce hataları düzeltin.");
    expect(html).not.toContain('id="map-warnings"');
    expect(html).not.toContain('id="map-errors"');
    expect(html).toContain("Örnek Fatura");
  });

  it("canlı karşılaştırma yapıldıysa farkın sayısı söylenir", () => {
    const html = screen({
      state: run([
        LOADED[0],
        LOADED[1],
        {
          type: "previewed",
          preview: previewResponse({
            db_check: { checked: true, missing_in_db: ["Satis.Cari"], only_in_db: [], message: null },
          }),
        },
      ]),
    });
    expect(html).toContain("Canlı veritabanıyla karşılaştırıldı: 1 farklılık.");
  });

  it("denetlemenin reddi sunucunun cümlesiyle #map-error'da durur", () => {
    const html = screen({
      state: run([LOADED[0], { type: "preview" }, { type: "fail", kind: "preview", message: "Yalnız .xlsx dosyası yüklenebilir." }]),
    });
    expect(html).toContain('id="map-error"');
    expect(html).toContain("Yalnız .xlsx dosyası yüklenebilir.");
    expect(html).not.toContain('id="map-progress"');
  });
});

describe("MapScreen — kümenin kurulması", () => {
  const APPLIED = [...LOADED, { type: "apply" }, { type: "job", job: job("writing") }];

  it("yazılırken ilk adım yanar, geçme düğmesi henüz yoktur", () => {
    const html = screen({ state: run(APPLIED) });
    expect(html).toContain('id="map-progress"');
    expect(html).toContain("●</span>Yazılıyor</li>");
    expect(html).toContain("○</span>İndeks kuruluyor</li>");
    expect(html).not.toContain('id="map-apply"');
    expect(html).not.toContain('id="map-activate"');
  });

  it("indeks kurulurken adım biter, sıradaki adım işaretlenir", () => {
    const html = screen({ state: run([...APPLIED, { type: "job", job: job("indexing") }]) });
    expect(html).toContain("✓</span>Yazılıyor</li>");
    expect(html).toContain('class="is-active"');
    expect(html).toContain("●</span>İndeks kuruluyor</li>");
  });

  it("iş düşerse cümlesi adım bandının içinde okunur", () => {
    const html = screen({
      state: run([...APPLIED, { type: "job", job: job("indexing") }, { type: "job", job: job("failed", "İndeks kurulumu çöktü.") }]),
    });
    expect(html).toContain('id="map-progress"');
    expect(html).toContain("İndeks kurulumu çöktü.");
    expect(html).not.toContain('id="map-error"');
    expect(html).not.toContain('id="map-activate"');
  });

  it("iş bitince üç adım dolar ve geçme düğmesi gelir", () => {
    const html = screen({ state: run([...APPLIED, { type: "job", job: job("indexing") }, { type: "job", job: job("done") }]) });
    expect(html).toContain("✓</span>Hazır</li>");
    expect(html).toContain('id="map-activate"');
    expect(html).toContain(">Bu veri kümesine geç</button>");
  });

  it("geçen küme söylenir, geçme düğmesi kalkar", () => {
    const html = screen({ state: run([{ type: "activated", name: "ornek_fatura" }]) });
    expect(html).toContain('id="map-activated"');
    expect(html).toContain("“ornek_fatura” etkin küme");
    expect(html).not.toContain('id="map-activate"');
  });

  it("geçiş reddi cümlesiyle döner", () => {
    const html = screen({ state: run([{ type: "switchError", message: "Bu kümenin veritabanı yok." }]) });
    expect(html).toContain('id="map-error"');
    expect(html).toContain("Bu kümenin veritabanı yok.");
  });
});

describe("MapScreen — veri kümeleri", () => {
  it("etkin küme rozetini taşır, kendisine geçilmez", () => {
    const html = screen({ datasets: DATASETS, active: "ornek_fatura" });
    expect(html).toContain('id="dataset-list"');
    expect(row(html, "ornek_fatura")).toContain(">Etkin</span>");
    expect(row(html, "ornek_fatura")).not.toContain("data-dataset-activate");
  });

  it("indeksi olmayan küme geçmeye kapalıdır, açıklaması ipucunda durur", () => {
    const html = screen({ datasets: DATASETS, active: "ornek_fatura" });
    expect(row(html, "wwi_real")).toContain("İndeks yok");
    expect(row(html, "wwi_real")).toMatch(/data-dataset-activate="wwi_real"[^>]*disabled/);
    expect(row(html, "wwi_real")).toContain("İndeks hiç kurulmamış.");
    expect(row(html, "wwi_real")).toContain(">SQL Server</span>");
  });

  it("bayat indeks uyarılır ama geçişe izin verir", () => {
    const html = screen({ datasets: DATASETS, active: "ornek_fatura" });
    expect(row(html, "synthetic_erp")).toContain("İndeks eski");
    expect(row(html, "synthetic_erp")).toContain('class="dataset-index is-stale"');
    expect(row(html, "synthetic_erp")).toMatch(/data-dataset-activate="synthetic_erp"[^>]*>/);
    expect(row(html, "synthetic_erp")).not.toMatch(/data-dataset-activate="synthetic_erp"[^>]*disabled/);
  });

  it("geçiş sürdüğünü tek satır söyler", () => {
    const html = screen({ datasets: DATASETS, active: "ornek_fatura", busy: "synthetic_erp" });
    expect(row(html, "synthetic_erp")).toContain(">Geçiliyor…</button>");
  });

  it("SQL Server kümesine geçişin duyurusu bağlantısıyla birlikte durur", () => {
    const notice = {
      name: "wwi_real",
      message: "Bu küme SQL Server'a bağlı: salt okunur girişi kurun ve sunucuyu NL2SQL_MSSQL_CONN ile başlatın.",
      login_script_url: "/api/datasets/wwi_real/login-script.sql",
      env: "NL2SQL_MSSQL_CONN",
    };
    const html = screen({ datasets: DATASETS, active: "wwi_real", notice });
    expect(html).toContain('id="dataset-notice"');
    expect(html).toContain("NL2SQL_MSSQL_CONN ile başlatın.");
    expect(html).toContain('href="/api/datasets/wwi_real/login-script.sql"');
    expect(screen({ datasets: DATASETS })).not.toContain('id="dataset-notice"');
  });

  it("geçişin reddi listenin üstünde sunucunun cümlesiyle durur", () => {
    const html = screen({
      datasets: DATASETS,
      active: "ornek_fatura",
      datasetsError: "Veritabanı dosyası yok: data/wwi_real.db.",
    });
    expect(html).toContain('id="dataset-error"');
    expect(html).toContain("Veritabanı dosyası yok: data/wwi_real.db.");
  });

  it("liste okunurken ve boşken ayrı cümle kurulur", () => {
    expect(screen({ datasets: [], datasetsLoading: true })).toContain("Kümeler okunuyor…");
    const empty = screen({ datasets: [] });
    expect(empty).toContain("Henüz veri kümesi yok.");
    expect(empty).not.toContain("okunuyor…");
  });
});

describe("MapFlow", () => {
  it("kapsayıcı ekranı sunucu yanıtı olmadan da kurar", () => {
    const html = render(<MapFlow />);
    expect(html).toContain('id="map-screen"');
    expect(html).toContain("Kümeler okunuyor…");
    expect(html).not.toContain("map-template-db");
  });
});

describe("App — Veritabanı haritası bağlantısı", () => {
  it("yalnız yönetici görür; kullanıcı ve tek kullanıcılı kabuk görmez", () => {
    const admin = render(<App user={{ username: "admin", role: "admin" }} />);
    expect(admin).toContain('id="nav-map"');
    expect(admin).toContain('href="#/harita"');
    expect(admin).toContain(">Veritabanı haritası</a>");

    for (const app of [render(<App user={{ username: "analist", role: "user" }} />), render(<App />)]) {
      expect(app).not.toContain('id="nav-map"');
      expect(app).not.toContain("#/harita");
    }
  });
});
