// ASSUMPTION: ret akışı olay + etki ister, SSR ikisini de çalıştırmaz; jsdom bu yüzden devDependency.
// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import RuleForm from "./RuleForm.jsx";
import RulesScreen from "./RulesScreen.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

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

const screen = (props) => render(<RulesScreen onRefresh={noop} {...props} />);
const form = (props) => render(<RuleForm onSaved={noop} onCancel={noop} {...props} />);

const RULES = [
  {
    id: "net_satis",
    term: "Net satış (iadeler düşülmüş)",
    synonyms: ["net satış", "iadeler düşülmüş satış"],
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
];

const TABLES = ["TBLSTHAR", "TBLFATUIRS", "TBLCASABIT"];

describe("RulesScreen", () => {
  it("başlığı, yeni kural düğmesini ve üç sütunlu listeyi kurar", () => {
    const html = screen({ rules: RULES, index: { fresh: true }, tables: TABLES });
    expect(html).toContain('id="rules-screen"');
    expect(html).toContain(">İş kuralları</h1>");
    expect(html).toContain('id="rule-add"');
    expect(html).toContain(">Yeni kural</button>");
    expect(html).toContain(">Terim</th>");
    expect(html).toContain(">Eş anlamlılar</th>");
    expect(html).toContain(">Tablolar</th>");
    expect(html).toContain("Net satış (iadeler düşülmüş)");
    expect(html).toContain('<span class="rules-id">net_satis</span>');
    expect(html).toContain("net satış, iadeler düşülmüş satış");
    expect(html).toContain("TBLSTHAR, TBLFATUIRS");
  });

  it("her satırda Düzenle ve Sil vardır; eş anlamlılar/sütun boşsa – okunur", () => {
    const html = screen({ rules: RULES, index: { fresh: true }, tables: TABLES });
    expect(html.match(/>Düzenle<\/button>/g)).toHaveLength(2);
    expect(html.match(/>Sil<\/button>/g)).toHaveLength(2);
    expect(html).not.toContain("Silinsin mi?");
    expect(html.match(/—/g)).toHaveLength(2);
  });

  it("boş liste iki halin sözünü ayırır: okunuyor / hiç kural yok", () => {
    expect(screen({ rules: [], index: { fresh: true }, loading: true })).toContain("Kurallar okunuyor…");
    const html = screen({ rules: [], index: { fresh: true } });
    expect(html).toContain("Henüz kural yok.");
    expect(html).not.toContain("Kurallar okunuyor…");
  });

  it("bayatlık bandı yalnız index.fresh false iken gelir ve yeniden kurmayı sunar", () => {
    const fresh = screen({ rules: RULES, index: { fresh: true, reason: null }, tables: TABLES });
    expect(fresh).not.toContain('id="index-stale"');
    expect(fresh).not.toContain('id="index-rebuild"');

    const stale = screen({
      rules: RULES,
      index: { fresh: false, reason: "Kuralların içeriği değişti." },
      tables: TABLES,
    });
    expect(stale).toContain('id="index-stale"');
    expect(stale).toContain("Kurallar değişti, indeks eski.");
    expect(stale).toContain("Kuralların içeriği değişti.");
    expect(stale).toContain('id="index-rebuild"');
    expect(stale).toContain(">İndeksi yeniden kur</button>");
    expect(stale).not.toContain("kuruluyor…");

    // indeks hiç okunmadıysa bandın kurulmaz: tazeliği bilinmiyor
    expect(screen({ rules: RULES })).not.toContain('id="index-stale"');
  });

  it("liste alanı hiç gelmese de ekran boş halini kurar", () => {
    const html = screen({ rules: null, index: undefined, tables: null });
    expect(html).toContain('id="rules-screen"');
    expect(html).toContain("Henüz kural yok.");
    expect(html).not.toContain("undefined");
  });
});

describe("RuleForm", () => {
  it("yeni kuralda boş alanlar, tablo için şemadan tamamlamalı datalist vardır", () => {
    const html = form({ tables: TABLES });
    expect(html).toContain('id="rule-form"');
    expect(html).toContain(">Yeni kural</h2>");
    expect(html).toContain('id="rule-save"');
    expect(html).toContain('list="table-options"');
    expect(html).toContain('id="table-options"');
    expect(html).toContain('<option value="TBLSTHAR"');
    expect(html).toContain('<option value="TBLCASABIT"');
    expect(html).toContain('id="rule-synonyms"');
    expect(html).toContain('id="rule-markers"');
    expect(html).not.toContain('id="rule-errors"');
  });

  it("düzenleme modunda kimlik kilitlidir ve kuralla dolu gelir", () => {
    const html = form({ rule: RULES[0], tables: TABLES });
    expect(html).toContain(">Kuralı düzenle</h2>");
    expect(html).toMatch(/id="rule-id"[^>]*disabled=""/);
    expect(html).toContain('value="net_satis"');
    expect(html).toContain("Net satış (iadeler düşülmüş)");
    expect(html).toContain("STHAR_HTUR\\s*=\\s*'S'");
    expect(form({})).toMatch(/id="rule-id"[^>]*value=""/);
    expect(form({})).not.toMatch(/id="rule-id"[^>]*disabled/);
  });

  it("sunucu hataları hem alanın altında hem #rule-errors özetinde durur", () => {
    const html = form({
      rule: RULES[0],
      tables: TABLES,
      errors: [
        { field: "term", message: "Terim boş olamaz." },
        { field: "tables", message: "Şemada olmayan tablo: TBLYOK." },
        { field: "markers", message: "İşaretçi derlenmiyor (geçersiz düzenli ifade): ((" },
      ],
    });
    expect(html).toContain('id="rule-errors"');
    expect(html.match(/Terim boş olamaz\./g)).toHaveLength(2);
    expect(html.match(/Şemada olmayan tablo: TBLYOK\./g)).toHaveLength(2);
    expect(html.match(/İşaretçi derlenmiyor/g)).toHaveLength(2);
    expect(html).toContain('id="rule-term-error"');
    expect(html).toContain('aria-describedby="rule-term-error"');
    expect(html).toContain('aria-invalid="true"');
    expect(html).toContain('<p class="field-error" id="rule-term-error">Terim boş olamaz.</p>');
  });

  it("alansız mesaj yalnız özettedir, alan hatası yoksa ipucu kalır", () => {
    const html = form({ errors: [{ message: "Kural kaydedilemedi." }] });
    expect(html).toContain('id="rule-errors"');
    expect(html).toContain("<li>Kural kaydedilemedi.</li>");
    expect(html).toContain('id="rule-term"');
    expect(html).toContain("Soruda geçen ad");
  });
});

// Rettin hissedilmesi olay istemi ister: özet ekrana *geldikten sonra* odaklanıp üstüne kayılmalı,
// sayı Kaydet'in yanında belirmeli. SSR ne olay ne etki çalıştırır, bu yüzden burada jsdom var.
describe("RuleForm — reddedilen kayıt", () => {
  let container;
  let root;
  let focus;
  let scrollIntoView;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    focus = vi.spyOn(HTMLElement.prototype, "focus");
    // jsdom scrollIntoView'u tanımaz; ölçülen çağrısı, kaydırmanın kendisi tarayıcının işi.
    scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    delete Element.prototype.scrollIntoView;
    vi.restoreAllMocks();
  });

  const open = (props = {}) => {
    act(() => root.render(<RuleForm onSaved={noop} onCancel={noop} tables={TABLES} {...props} />));
  };

  const submit = () => {
    act(() => {
      const event = new Event("submit", { bubbles: true, cancelable: true });
      container.querySelector("#rule-form").dispatchEvent(event);
    });
  };

  it("boş form reddedilince özet odaklanıp üstüne kayılır, sayı düğmenin yanında belirir", () => {
    open();
    expect(container.querySelector("#rule-errors")).toBeNull();
    expect(container.querySelector("#rule-error-count")).toBeNull();

    submit();

    const errors = container.querySelector("#rule-errors");
    expect(errors.getAttribute("tabindex")).toBe("-1");
    expect(focus).toHaveBeenCalledTimes(1);
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(errors);
    expect(container.querySelector("#rule-error-count").textContent).toBe("3 alan hatalı");
  });

  it("açılışta odak çalınmaz; ikinci ret özetin üstüne yeniden çıkar, alansız mesajda sayı yoktur", () => {
    open({ errors: [{ message: "Kural kaydedilemedi." }] });
    expect(container.querySelector("#rule-errors")).toBeTruthy();
    expect(container.querySelector("#rule-error-count")).toBeNull();
    expect(focus).not.toHaveBeenCalled();
    expect(scrollIntoView).not.toHaveBeenCalled();

    submit();

    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    expect(document.activeElement).toBe(container.querySelector("#rule-errors"));
    expect(container.querySelector("#rule-error-count").textContent).toBe("3 alan hatalı");
  });
});
