// @vitest-environment jsdom
// T437 (R8-20): kural ekranının ve formunun kabarı iki dilde. İki dil aynı id kümesini boyar;
// İngilizce çıktının kabarı Türkçe harf taşımaz — verinin kendisi (terim, eş anlamlı, tablo adı)
// çevrilmez, o yüzden İngilizce geçiş İngilizce veriyle yapılır. Türkçe çıktı bugünkü cümleleri
// harfi harfine verir: RulesScreen.test.jsx ve RulesReadOnly.test.jsx o cümleleri bekliyor.
// Eş anlamlıların İngilizce listesi (`synonyms_en`, R8-13) formda #rule-synonyms-en, satırda
// Türkçe listenin altındaki satırdır; payload'a yalnız doluysa girer — sunucu da alanı doluysa
// yazar (rules_edit.normalize_rule), o yüzden boş bırakılan alan kaydı eski hâline döner.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import en from "../i18n/en.json";
import { I18nProvider } from "../i18n/index.js";
import tr from "../i18n/tr.json";
import * as api from "../lib/api.js";
import { DEFINITION_MESSAGE, ID_MESSAGE, TERM_MESSAGE, fromForm, toForm } from "../lib/rulesForm.js";
import RuleForm from "./RuleForm.jsx";
import RulesScreen from "./RulesScreen.jsx";

// Kayıt istekleri ağa çıkmaz: gövde olduğu gibi geri döner, payload oradan okunur.
vi.mock("../lib/api.js", async (importOriginal) => ({
  ...(await importOriginal()),
  rulesCreate: vi.fn(async (body) => body),
  rulesUpdate: vi.fn(async (id, body) => ({ id, ...body })),
  rulesRemove: vi.fn(async () => ({ ok: true })),
  rebuild: vi.fn(async () => ({ ok: true })),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const noop = () => {};
const TURKISH = /[çğıöşüÇĞİÖŞÜ]/;
const TABLES = ["TBLSTHAR", "TBLFATUIRS"];

// Aynı iki kuralın iki dildeki hâli: id'ler ortak, kabuk değil veri çevriliyor.
const RULES = {
  tr: [
    {
      id: "net_satis",
      term: "Net satış (iadeler düşülmüş)",
      synonyms: ["net satış", "iadeler düşülmüş satış"],
      synonyms_en: ["net sales", "net revenue"],
      definition: "Satıştan iadelerin düşüldüğü hal.",
      sql_hint: "SUM(...)",
      tables: ["TBLSTHAR", "TBLFATUIRS"],
      markers: ["STHAR_HTUR\\s*=\\s*'S'"],
    },
    {
      id: "gecen_ay",
      term: "Geçen ay",
      synonyms: [],
      definition: "Takvim ayı.",
      sql_hint: "",
      tables: [],
      markers: [],
    },
  ],
  en: [
    {
      id: "net_satis",
      term: "Net sales (returns deducted)",
      synonyms: ["net sales", "sales after returns"],
      synonyms_en: ["net sales", "net revenue"],
      definition: "Sales with the returns taken out.",
      sql_hint: "SUM(...)",
      tables: ["TBLSTHAR", "TBLFATUIRS"],
      markers: ["STHAR_HTUR\\s*=\\s*'S'"],
    },
    {
      id: "gecen_ay",
      term: "Last month",
      synonyms: [],
      definition: "The calendar month.",
      sql_hint: "",
      tables: [],
      markers: [],
    },
  ],
};

const STALE = { fresh: false, reason: "Kuralların içeriği değişti." };

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

const screen = (lang, props = {}) =>
  inLang(lang, <RulesScreen rules={RULES[lang]} index={{ fresh: true }} tables={TABLES} onRefresh={noop} {...props} />);
const form = (lang, props = {}) =>
  inLang(lang, <RuleForm tables={TABLES} onSaved={noop} onCancel={noop} {...props} />);

let container;
let root;

async function mount(node) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(node));
  return container;
}

function unmount() {
  act(() => root.unmount());
  container.remove();
  container = undefined;
  root = undefined;
}

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

// Kontrollü girdi: React'ın değer izleyicisini dolaşmak için yerleşik setter'a yazılır.
function type(node, value) {
  const proto = node.tagName === "TEXTAREA" ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, "value").set.call(node, value);
  node.dispatchEvent(new Event("input", { bubbles: true }));
}

async function submit(app) {
  await act(async () => {
    app.querySelector("#rule-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  await settle();
}

afterEach(() => {
  if (root) unmount();
});

describe("kural ekranı iki dilde", () => {
  it("aynı id kümesini boyar: çeviri markup'ı değiştirmez", () => {
    const base = ids(screen("tr"));
    expect(base).toContain("rules-screen");
    expect(base).toContain("rule-add");
    expect(ids(screen("en"))).toEqual(base);

    expect(ids(screen("en", { readOnly: true }))).toEqual(ids(screen("tr", { readOnly: true })));
    expect(ids(screen("en", { index: STALE }))).toEqual(ids(screen("tr", { index: STALE })));
    expect(ids(screen("en", { rules: [] }))).toEqual(ids(screen("tr", { rules: [] })));
    expect(ids(form("en"))).toEqual(ids(form("tr")));
    expect(ids(form("en", { rule: RULES.en[0] }))).toEqual(ids(form("tr", { rule: RULES.tr[0] })));
  });

  it("İngilizce kabuk Türkçe harf ve bugünün cümlesini taşımıyor", () => {
    const html = screen("en");
    expect(html).not.toMatch(TURKISH);
    for (const text of [
      ">Business rules</h1>",
      ">New rule</button>",
      ">Synonyms</th>",
      ">Tables</th>",
      ">Actions</th>",
      ">Edit</button>",
      ">Delete</button>",
      "Rules decide what a term in a question means for Bilgin.",
    ]) {
      expect(html).toContain(text);
    }
    for (const text of [">İş kuralları<", ">Yeni kural</button>", ">Eş anlamlılar</th>", ">İşlem</th>", ">Düzenle<"]) {
      expect(html).not.toContain(text);
    }

    const stale = screen("en", { index: STALE });
    expect(stale).toContain("The rules changed; the index is out of date.");
    expect(stale).toContain(">Rebuild the index</button>");
    expect(screen("en", { rules: [] })).toContain("No rules yet. Add one with “New rule”.");
    expect(screen("en", { readOnly: true })).toContain("Only an administrator can change the business rules.");
  });

  it("Türkçe ekran bugünkü cümleleri harfi harfine veriyor ve provider'sız haliyle aynı", () => {
    const html = screen("tr");
    for (const text of [
      ">İş kuralları</h1>",
      ">Yeni kural</button>",
      ">Terim</th>",
      ">Eş anlamlılar</th>",
      ">Tablolar</th>",
      ">İşlem</th>",
      ">Düzenle</button>",
      ">Sil</button>",
      "Kurallar, Bilgin'in bir soruda hangi terimi ne anladığını belirler.",
    ]) {
      expect(html).toContain(text);
    }
    expect(render(<RulesScreen rules={RULES.tr} index={{ fresh: true }} tables={TABLES} onRefresh={noop} />)).toBe(html);
    expect(screen("tr", { index: STALE })).toContain("Kurallar değişti, indeks eski.");
    expect(screen("tr", { rules: [] })).toContain("Henüz kural yok. “Yeni kural” ile ekleyin.");
    expect(screen("tr", { readOnly: true })).toContain("İş kurallarını yalnız yönetici değiştirebilir.");
  });

  it("eş anlamlıların İngilizce satırı iki dilde de Türkçe listenin altında duruyor", () => {
    for (const lang of ["tr", "en"]) {
      const html = screen(lang);
      expect(html).toContain('<span class="rules-synonyms-en" lang="en"><span class="rules-synonyms-en-tag">EN</span>');
      expect(html).toContain(">EN</span>net sales, net revenue</span>");
    }
    // Eş anlamlısı olmayan kural satırın ikincisini kurmaz; boş hücre yine – okunur.
    expect(screen("en", { rules: [RULES.en[1]] })).not.toContain("rules-synonyms-en-tag");
    expect(screen("en", { rules: [RULES.en[1]] })).toContain('<td class="rules-list">—</td>');
  });
});

describe("kural formu iki dilde", () => {
  it("boş formda #rule-synonyms-en boş gelir, düzenlemede virgüllü listesiyle dolar", () => {
    for (const lang of ["tr", "en"]) {
      const empty = form(lang);
      expect(empty).toContain('id="rule-synonyms-en"');
      expect(empty).toMatch(/id="rule-synonyms-en"[^>]*value=""/);
      const editing = form(lang, { rule: RULES[lang][0] });
      expect(editing).toMatch(/id="rule-synonyms-en"[^>]*value="net sales, net revenue"/);
      expect(editing).toContain(`for="rule-synonyms-en"`);
    }
    expect(form("tr")).toContain('>Eş anlamlılar (İngilizce)</label>');
    expect(form("en")).toContain(">Synonyms (English)</label>");
    expect(form("en")).not.toMatch(TURKISH);
    expect(form("tr")).toContain(">Kimlik</label>");
    expect(form("en")).toContain(">Identifier</label>");
    expect(form("en")).toContain(">SQL hint</label>");
    expect(form("tr")).toContain(">SQL ipucu</label>");
  });

  it("başlıklar, düğmeler ve ipuçları iki dilde; Türkçe hali provider'sızla aynı", () => {
    const trNew = form("tr");
    expect(render(<RuleForm tables={TABLES} onSaved={noop} onCancel={noop} />)).toBe(trNew);
    expect(trNew).toContain(">Yeni kural</h2>");
    expect(trNew).toContain(">Kaydet</button>");
    expect(trNew).toContain(">Vazgeç</button>");
    expect(trNew).toContain("Virgülle ayırın: net sales, revenue. Zorunlu değil.");
    const enNew = form("en");
    expect(enNew).toContain(">New rule</h2>");
    expect(enNew).toContain(">Save</button>");
    expect(enNew).toContain(">Cancel</button>");
    expect(enNew).toContain("Separate with commas: net sales, revenue. Optional.");

    expect(form("tr", { rule: RULES.tr[0] })).toContain(">Kuralı düzenle</h2>");
    expect(form("en", { rule: RULES.en[0] })).toContain(">Edit the rule</h2>");
    expect(form("en", { rule: RULES.en[0] })).toContain("Saving makes the index stale;");
  });

  it("sunucunun reddi olduğu gibi kalır, alan hatası dilin cümlesidir", () => {
    const server = [{ field: "tables", message: "Şemada olmayan tablo: TBLYOK." }];
    expect(form("en", { errors: server })).toContain("Şemada olmayan tablo: TBLYOK.");
    expect(form("en", { errors: server })).toContain(">Could not save — fix these:</p>");
    expect(form("tr", { errors: server })).toContain(">Kaydedilemedi — şunları düzeltin:</p>");
  });
});

describe("eş anlamlılar (İngilizce) payload'a dönüyor", () => {
  it("yeni kural listeyi synonyms_en olarak gönderiyor, boş alan alanı hiç taşımıyor", async () => {
    for (const lang of ["tr", "en"]) {
      api.rulesCreate.mockClear();
      const app = await mount(<I18nProvider lang={lang}>{formShell()}</I18nProvider>);
      type(app.querySelector("#rule-id"), "net_satis");
      type(app.querySelector("#rule-term"), "Net satış");
      type(app.querySelector("#rule-definition"), "Satıştan iadelerin düşüldüğü hal.");
      type(app.querySelector("#rule-synonyms-en"), "net sales, , net revenue");
      await submit(app);
      expect(api.rulesCreate).toHaveBeenCalledWith({
        id: "net_satis",
        term: "Net satış",
        synonyms: [],
        definition: "Satıştan iadelerin düşüldüğü hal.",
        sql_hint: "",
        tables: [],
        markers: [],
        synonyms_en: ["net sales", "net revenue"],
      });
      unmount();
    }

    // Boş bırakılan alan payload'a hiç girmiyor: sunucu da alanı yalnız doluysa yazar.
    api.rulesCreate.mockClear();
    const app = await mount(<I18nProvider lang="en">{formShell()}</I18nProvider>);
    type(app.querySelector("#rule-id"), "gecen_ay");
    type(app.querySelector("#rule-term"), "Last month");
    type(app.querySelector("#rule-definition"), "The calendar month.");
    await submit(app);
    expect(api.rulesCreate.mock.calls[0][0]).not.toHaveProperty("synonyms_en");
    unmount();
  });

  it("düzenleme kuralı bulup listesiyle açıyor ve güncellemeye aynı alanı yazıyor", async () => {
    api.rulesUpdate.mockClear();
    const app = await mount(
      <I18nProvider lang="en">{formShell({ rule: RULES.en[0] })}</I18nProvider>,
    );
    expect(app.querySelector("#rule-synonyms-en").value).toBe("net sales, net revenue");
    expect(app.querySelector("#rule-id").disabled).toBe(true);
    type(app.querySelector("#rule-synonyms-en"), "net sales");
    await submit(app);
    expect(api.rulesUpdate).toHaveBeenCalledWith("net_satis", expect.objectContaining({ synonyms_en: ["net sales"] }));
    unmount();
  });

  it("kayıt -> form -> kayıt turu listeyi koruyor, taşımayan kuralı oldugu gibi bırakıyor", () => {
    expect(fromForm(toForm(RULES.en[0]))).toEqual(RULES.en[0]);
    expect(toForm(RULES.en[1])).not.toHaveProperty("synonyms_en");
    expect(fromForm(toForm(RULES.en[1]))).toEqual(RULES.en[1]);
  });
});

describe("reddin cümlesi iki dilde", () => {
  it("boş formun üç alan hatası arayüzün dilinde okunuyor", async () => {
    const messages = {
      tr: [ID_MESSAGE, TERM_MESSAGE, DEFINITION_MESSAGE],
      en: [
        "The id may contain only lowercase letters, digits and underscores (e.g. net_satis).",
        "The term cannot be empty.",
        "The definition cannot be empty.",
      ],
    };
    for (const lang of ["tr", "en"]) {
      const app = await mount(<I18nProvider lang={lang}>{formShell()}</I18nProvider>);
      expect(app.querySelector("#rule-errors")).toBeNull();
      await submit(app);
      const items = [...app.querySelectorAll(".rule-errors-list li")].map((node) => node.textContent);
      expect(items).toEqual(messages[lang]);
      expect(app.querySelector("#rule-error-count").textContent).toBe(
        lang === "tr" ? "3 alan hatalı" : "3 fields have errors",
      );
      expect(app.querySelector("#rule-synonyms-en-error")).toBeNull();
      unmount();
    }
  });

  it("tek hatalı alan İngilizcede tekli okunuyor", async () => {
    const app = await mount(<I18nProvider lang="en">{formShell()}</I18nProvider>);
    type(app.querySelector("#rule-id"), "net_satis");
    type(app.querySelector("#rule-term"), "Last month");
    await submit(app);
    expect(app.querySelector("#rule-error-count").textContent).toBe("1 field has errors");
    expect(app.querySelector("#rule-definition-error").textContent).toBe("The definition cannot be empty.");
    unmount();
  });

  it("üç sabit Türkçe katalog değerinin kendisidir: çeviri iki yerde yazılmıyor", () => {
    expect(ID_MESSAGE).toBe(tr["rules.form.idPattern"]);
    expect(TERM_MESSAGE).toBe(tr["rules.form.termEmpty"]);
    expect(DEFINITION_MESSAGE).toBe(tr["rules.form.definitionEmpty"]);
    expect(en["rules.field.synonymsEn"]).toBe("Synonyms (English)");
  });
});

// Form tek başına da ağaçlanabilir; sarmalayıcı yalnız provider'ın altına koymak için.
function formShell(props = {}) {
  return <RuleForm tables={TABLES} onSaved={noop} onCancel={noop} {...props} />;
}
