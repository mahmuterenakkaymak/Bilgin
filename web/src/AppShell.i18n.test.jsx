// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// R8-17: başlık ve kabuk iki dilde. Yönetici kabuğu tr ve en'de aynı id kümesini boyamalı,
// İngilizce başlıkta Türkçe harf kalmamalı, Türkçe çıktı bugünkü cümleleri harfi harfine
// vermeli — App.test.jsx, Root.test.jsx ve UsersBusinessRole.test.jsx o cümleleri bekliyor.
// Temizlik kapsamı başlık ve kabuğun kendi çervesi: kenar çubuğunun listeleri (T436) ve soru
// ekranının kartları (T434/T440) kendi görevlerinde çevriliyor. Sunucunun cümleleri (reddin
// detail'i, sürücü hatası) çevrilmez, verildiği dilde okunur.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import App from "./App.jsx";
import DatasetList from "./components/DatasetList.jsx";
import { DbBanner, DbDot } from "./components/DbStatus.jsx";
import EmptyState from "./components/EmptyState.jsx";
import MastheadNav from "./components/MastheadNav.jsx";
import { I18nProvider } from "./i18n/index.js";

const TURKISH = /[çğıöşüÇĞİÖŞÜ]/;
const ADMIN = { username: "admin", role: "admin", business_role: "muhasebe" };
const noop = () => {};

// Cümlelerdeki kesme işareti ve tırnak SSR çıktısında düz karakter değildir; okunur metin öyle aranır.
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
const shell = (lang) => inLang(lang, <App user={ADMIN} onLogout={noop} />);
const bareShell = () => render(<App user={ADMIN} onLogout={noop} />);
const masthead = (lang) => /<header[\s\S]*?<\/header>/.exec(shell(lang))[0];

describe("yönetici kabuğu iki dilde", () => {
  it("aynı id kümesini boyar: çeviri markup'ı değiştirmez", () => {
    const tr = ids(shell("tr"));
    expect(tr).toContain("user-chip");
    expect(ids(shell("en"))).toEqual(tr);
  });

  it("İngilizce başlıkta Türkçe harf kalmıyor", () => {
    expect(masthead("en")).not.toMatch(TURKISH);
  });

  it("İngilizce başlık çevrildiği cümleleri söylüyor", () => {
    const html = masthead("en");
    for (const text of [
      ">Ask</a>",
      ">Rules</a>",
      ">Map</a>",
      ">Connections</a>",
      ">Ready</a>",
      ">Users</a>",
      ">System</button>",
      ">Unknown</span>",
      ">Database</a>",
      ">admin · Accounting · Admin</span>",
      ">Sign out</button>",
      'aria-label="Sections"',
      'aria-label="Theme: System. Activate to change."',
      'title="Signed-in user"',
    ]) {
      expect(html).toContain(text);
    }
  });

  it("Türkçe başlık bugünkü metni harfi harfine veriyor", () => {
    const html = masthead("tr");
    for (const text of [
      ">Sor</a>",
      ">Kurallar</a>",
      ">Harita</a>",
      ">Bağlantılar</a>",
      ">Hazır</a>",
      ">Kullanıcılar</a>",
      ">Sistem</button>",
      ">Bilinmiyor</span>",
      ">Veritabanı</a>",
      ">admin · Muhasebe · Yönetici</span>",
      ">Çıkış</button>",
      'aria-label="Bölümler"',
      'aria-label="Tema: Sistem. Değiştirmek için etkinleştir."',
      'title="Oturum sahibi"',
    ]) {
      expect(html).toContain(text);
    }
  });

  it("provider'sız kabuk tr katalogla aynı baytı üretir", () => {
    expect(bareShell()).toBe(shell("tr"));
  });

  it("çekmecenin düğmesi ve erişim adı da çevriliyor", () => {
    expect(shell("en")).toContain(">Saved and history</button>");
    expect(shell("en")).toContain('aria-label="Saved and history"');
    expect(shell("tr")).toContain(">Kayıtlılar ve geçmiş</button>");
    expect(shell("tr")).toContain('aria-label="Kayıtlılar ve geçmiş"');
  });
});

describe("gezinme satırı iki dilde", () => {
  const nav = (lang) => inLang(lang, <MastheadNav route="rules" user={ADMIN} />);

  it("İngilizce satırda Türkçe harf yok, adresler aynı", () => {
    const html = nav("en");
    expect(html).not.toMatch(TURKISH);
    expect(html).toContain('href="#/hazir-sorular"');
    expect(html).toContain('aria-current="page"');
  });

  it("Türkçe satır bugünkü adları veriyor", () => {
    expect(nav("tr")).toContain(">Hazır</a>");
    expect(render(<MastheadNav route="rules" user={ADMIN} />)).toBe(nav("tr"));
  });
});

describe("veritabanı noktası ve bandı iki dilde", () => {
  const CHECKED = "2026-10-27T09:15:00+00:00";
  const ok = { state: "ok", checked_at: CHECKED };
  // Sunucunun cümlesi çevrilmez: sürücü satırı ve reddin cümlesi geldiği gibi yazılır.
  const down = {
    state: "down",
    checked_at: CHECKED,
    message: "Cannot reach the database.",
    message_admin: "TCP Provider: No connection could be made.",
  };

  it("nokta iki dilde de aynı id'leri boyuyor ve İngilizce temiz", () => {
    const tr = ids(inLang("tr", <DbDot db={ok} isAdmin />));
    expect(ids(inLang("en", <DbDot db={ok} isAdmin />))).toEqual(tr);
    expect(inLang("en", <DbDot db={ok} isAdmin />)).not.toMatch(TURKISH);
    expect(inLang("tr", <DbDot db={ok} isAdmin />)).toContain(">Veritabanı</a>");
  });

  it("İngilizce ipucu saati kendi diliyle ve katalog cümlesiyle söylüyor", () => {
    const html = inLang("en", <DbDot db={ok} />);
    expect(html).toContain("Last checked:");
    expect(html).toContain("The database is responding.");
    expect(inLang("tr", <DbDot db={ok} />)).toContain("Son kontrol:");
  });

  it("bant iki dilde yalnız düşmüş halde açılıyor ve yöneticiye adresi veriyor", () => {
    expect(inLang("en", <DbBanner db={ok} isAdmin />)).toBe("");
    const en = inLang("en", <DbBanner db={down} isAdmin />);
    expect(en).toContain("Cannot reach the database.");
    expect(en).toContain(">Edit the connection</a>");
    expect(en).not.toMatch(TURKISH);
    expect(inLang("tr", <DbBanner db={down} isAdmin />)).toContain(">Bağlantıyı düzenle</a>");
  });
});

describe("veri kümesi listesi iki dilde", () => {
  const DATASETS = [
    { name: "wwi", display_name: "WWI", connection: "sqlite", active: true, index: { exists: true, fresh: true } },
    {
      name: "synthetic_erp",
      display_name: "Synthetic ERP",
      connection: "mssql",
      active: false,
      index: { exists: true, fresh: false, reason: "rules changed" },
    },
    { name: "mini", display_name: "", connection: "sqlite", active: false, index: { exists: false } },
  ];
  const list = (lang) => inLang(lang, <DatasetList datasets={DATASETS} active="wwi" onActivate={noop} />);

  it("aynı satırları boyuyor, İngilizce çıktıda Türkçe harf yok", () => {
    expect(ids(list("en"))).toEqual(ids(list("tr")));
    expect(list("en")).not.toMatch(TURKISH);
  });

  it("İngilizce indeks halleri ve düğme adları okunuyor", () => {
    const html = list("en");
    for (const text of [">Active</span>", "Index out of date", "Index ready", "No index", ">Use this dataset</button>"]) {
      expect(html).toContain(text);
    }
    expect(html).toContain("build its index before switching");
  });

  it("Türkçe liste bugünkü adları veriyor", () => {
    const html = list("tr");
    for (const text of [">Etkin</span>", "İndeks eski", "İndeks hazır", "İndeks yok", ">Bu kümeye geç</button>"]) {
      expect(html).toContain(text);
    }
    expect(render(<DatasetList datasets={DATASETS} active="wwi" onActivate={noop} />)).toBe(html);
  });

  it("boş ve yüklenen halleri de çevrili", () => {
    expect(inLang("en", <DatasetList loading onActivate={noop} />)).toContain("Reading datasets…");
    expect(inLang("en", <DatasetList error="Boom." onActivate={noop} />)).toContain("Datasets could not be read.");
    expect(inLang("en", <DatasetList onActivate={noop} />)).toContain("No datasets yet.");
    expect(inLang("tr", <DatasetList onActivate={noop} />)).toContain("Henüz veri kümesi yok.");
  });
});

describe("boş ekran iki dilde", () => {
  const EXAMPLES = [{ question: "Top five products?", kind: "golden" }];
  // Cümle ve kural bağlantısı çip sırası yokken okunur: örnek gelirse alt yarı hiç boyanmaz.
  const empty = (lang) =>
    inLang(lang, <EmptyState examples={[]} datasetName="WWI" rulesHint onSelect={noop} />);

  it("İngilizce kartta Türkçe harf kalmıyor, kural bağlantısı aynı adreste", () => {
    const html = empty("en");
    expect(html).not.toMatch(TURKISH);
    expect(html).toContain("Ask your data in plain language");
    expect(html).toContain("You are asking over «WWI»");
    expect(html).toContain('href="#/kurallar"');
    expect(html).toContain(">Business rules</a>");
    expect(html).toContain('from the <a href="#/kurallar">Business rules</a> screen.');
  });

  it("Türkçe kart bugünkü cümleleri ve bitişik yarısını koruyor", () => {
    const html = empty("tr");
    expect(html).toContain("Verinize Türkçe soru sorun");
    expect(html).toContain("«WWI» üzerinde soruyorsun; örnekler onun tablolarından.");
    expect(html).toContain("çevirir. Kümenin iş kuralı da yok");
    expect(html).toContain('için <a href="#/kurallar">İş kuralları</a> ekranından ilk kuralını ekle.');
    expect(render(<EmptyState examples={[]} datasetName="WWI" rulesHint onSelect={noop} />)).toBe(html);
  });

  it("ad yoksa genel lead, örnek varsa çipler duruyor", () => {
    const html = inLang("en", <EmptyState examples={EXAMPLES} onSelect={noop} />);
    expect(html).toContain("Bilgin writes the SQL, then shows the result and how it was computed.");
    expect(html).toContain(">Top five products?</button>");
    expect(html).not.toContain("empty-hint");
  });
});
