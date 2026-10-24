import { describe, expect, it } from "vitest";
import { DEFINITION_MESSAGE, ID_MESSAGE, TERM_MESSAGE, clientErrors, fromForm, mergeErrors, toForm } from "./rulesForm.js";

const RULE = {
  id: "net_satis",
  term: "Net satış (iadeler düşülmüş)",
  synonyms: ["net satış", "iadeler düşülmüş satış"],
  definition: "Satış miktarından iadelerin düşüldüğü hal.",
  sql_hint: "SUM(CASE WHEN h.STHAR_HTUR = 'S' THEN h.STHAR_GCMIK ELSE -h.STHAR_GCMIK END)",
  tables: ["TBLSTHAR", "TBLFATUIRS"],
  markers: ["STHAR_HTUR\\s*=\\s*'S'", "STHAR_HTUR\\s*=\\s*'I'"],
};

describe("toForm", () => {
  it("listeleri formun virgüllü metinlerine çevirir", () => {
    const form = toForm(RULE);
    expect(form.id).toBe("net_satis");
    expect(form.synonyms).toBe("net satış, iadeler düşülmüş satış");
    expect(form.tables).toBe("TBLSTHAR, TBLFATUIRS");
    expect(form.definition).toBe(RULE.definition);
    expect(form.sql_hint).toBe(RULE.sql_hint);
  });

  it("işaretçileri satır başına bir düzenli ifade yapar", () => {
    expect(toForm(RULE).markers).toBe("STHAR_HTUR\\s*=\\s*'S'\nSTHAR_HTUR\\s*=\\s*'I'");
  });

  it("alanı olmayan kayıt boş form kurar, ekran asla undefined görmez", () => {
    for (const form of [toForm(undefined), toForm(null), toForm({}), toForm({ synonyms: null, tables: "TBL" })]) {
      expect(Object.values(form).every((value) => typeof value === "string")).toBe(true);
      expect(JSON.stringify(form)).not.toMatch(/undefined|null/);
    }
    expect(toForm({ id: "x" })).toEqual({
      id: "x",
      term: "",
      synonyms: "",
      definition: "",
      sql_hint: "",
      tables: "",
      markers: "",
    });
  });
});

describe("fromForm", () => {
  it("virgüllü alanları listeye, işaretçileri satırlara böler ve kırpır", () => {
    const rule = fromForm({
      id: "  iade_orani  ",
      term: " İade oranı ",
      synonyms: " iade oranı , ,iade yüzdesi ",
      definition: " İade miktarının satışa oranı. ",
      sql_hint: "",
      tables: "TBLSTHAR,,TBLFATUIRS",
      markers: "A\r\n B \r\n",
    });
    expect(rule).toEqual({
      id: "iade_orani",
      term: "İade oranı",
      synonyms: ["iade oranı", "iade yüzdesi"],
      definition: "İade miktarının satışa oranı.",
      sql_hint: "",
      tables: ["TBLSTHAR", "TBLFATUIRS"],
      markers: ["A", "B"],
    });
  });

  it("boş form eksik listelerle değil boş listelerle döner", () => {
    expect(fromForm({})).toEqual({
      id: "",
      term: "",
      synonyms: [],
      definition: "",
      sql_hint: "",
      tables: [],
      markers: [],
    });
  });

  it("kayıt -> form -> kayıt turu veriyi korur", () => {
    expect(fromForm(toForm(RULE))).toEqual(RULE);
  });
});

describe("clientErrors", () => {
  it("boş formda sunucunun üç zorunlu alan mesajını verir", () => {
    expect(clientErrors({})).toEqual({ id: ID_MESSAGE, term: TERM_MESSAGE, definition: DEFINITION_MESSAGE });
    expect(clientErrors()).toEqual(clientErrors({}));
  });

  it("kalıba uymayan kimlik ile boş terim ayrı ayrı işaretlenir", () => {
    expect(clientErrors({ id: "Net Satis", term: "  ", definition: "Tanım var." })).toEqual({
      id: ID_MESSAGE,
      term: TERM_MESSAGE,
    });
    expect(clientErrors({ id: "net_satis", term: "Net satış", definition: "  " })).toEqual({
      definition: DEFINITION_MESSAGE,
    });
  });

  it("temiz kuralla hata üretmez", () => {
    expect(clientErrors(toForm(RULE))).toEqual({});
  });
});

describe("mergeErrors", () => {
  it("422 gövdesini alanın altına yazılacak sözlüğe indirir", () => {
    expect(
      mergeErrors([
        { field: "id", message: "Bu kimlikte bir kural zaten var: ciro." },
        { field: "tables", message: "Şemada olmayan tablo: TBLYOK." },
      ]),
    ).toEqual({ id: "Bu kimlikte bir kural zaten var: ciro.", tables: "Şemada olmayan tablo: TBLYOK." });
  });

  it("aynı alanın birden çok mesajı tek satırda birleşir, alansız mesaj özettedir", () => {
    expect(
      mergeErrors([
        { field: "tables", message: "Şemada olmayan tablo: A." },
        { field: "tables", message: "Şemada olmayan tablo: B." },
        { message: "Kural kaydedilemedi." },
        { field: "markers", message: "  " },
      ]),
    ).toEqual({ tables: "Şemada olmayan tablo: A. Şemada olmayan tablo: B.", "": "Kural kaydedilemedi." });
  });

  it("liste olmayan ya da boş gövde boş sözlük verir", () => {
    expect(mergeErrors(undefined)).toEqual({});
    expect(mergeErrors(null)).toEqual({});
    expect(mergeErrors("hata")).toEqual({});
    expect(mergeErrors([])).toEqual({});
  });
});
