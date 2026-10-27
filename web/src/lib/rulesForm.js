// Kural formunun iki yüzü arasında çeviri: API kaydı (listeler) <-> form (tek satır metinler).
// Zorunlu alan mesajları sunucudakiyle (schema_map/rules_edit.py) birebir aynı yazılır ki
// kullanıcı boş formu göndermek için bir gidiş-gerişi beklemesin (R5-18). Mesajlar R8-20'de
// kataloğa taşındı; aşağıdaki üç sabit Türkçe katalog değerlerinin kendisidir — sunucunun tr
// cümleleriyle de aynı olduğu için testler bu sabitleri beklemeye devam ediyor.
import { makeT } from "../i18n/index.js";

const ID_PATTERN = /^[a-z0-9_]+$/;

export const ID_MESSAGE = "Kimlik yalnız küçük harf, rakam ve alt çizgiden oluşmalı (ör. net_satis).";
export const TERM_MESSAGE = "Terim boş olamaz.";
export const DEFINITION_MESSAGE = "Tanım boş olamaz.";

const MESSAGE_KEYS = {
  id: "rules.form.idPattern",
  term: "rules.form.termEmpty",
  definition: "rules.form.definitionEmpty",
};

export function toForm(rule) {
  const item = rule ?? {};
  const form = {
    id: text(item.id),
    term: text(item.term),
    synonyms: items(item.synonyms).join(", "),
    definition: text(item.definition),
    sql_hint: text(item.sql_hint),
    tables: items(item.tables).join(", "),
    // ASSUMPTION: işaretçiler formda satır başına bir düzenli ifade — virgülle ayrılsa `\\d{1,3}` bölünür.
    markers: items(item.markers).join("\n"),
  };
  // ASSUMPTION: `synonyms_en` (R8-13) yalnız kayıtta doluysa forma girer — sunucu da alanı doluysa
  // yazar; taşımayan bir kural formdan geçtiği halde diske döner.
  const english = items(item.synonyms_en);
  if (english.length) form.synonyms_en = english.join(", ");
  return form;
}

export function fromForm(form) {
  const item = form ?? {};
  const rule = {
    id: text(item.id).trim(),
    term: text(item.term).trim(),
    synonyms: commas(item.synonyms),
    definition: text(item.definition).trim(),
    sql_hint: text(item.sql_hint).trim(),
    tables: commas(item.tables),
    markers: lines(item.markers),
  };
  const english = commas(item.synonyms_en);
  if (english.length) rule.synonyms_en = english;
  return rule;
}

// `lang` arayüzün dili: boş formun reddi sunucuya varmadan kullanıcının dilinde okunur.
export function clientErrors(form, lang = "tr") {
  const t = makeT(lang);
  const item = form ?? {};
  const errors = {};
  if (!ID_PATTERN.test(text(item.id).trim())) errors.id = t(MESSAGE_KEYS.id);
  if (!text(item.term).trim()) errors.term = t(MESSAGE_KEYS.term);
  if (!text(item.definition).trim()) errors.definition = t(MESSAGE_KEYS.definition);
  return errors;
}

// 422 gövdesindeki [{"field","message"}] listesi alanın altına yazılacak sözlüğe iner; aynı
// alanın birden çok mesajı (ör. iki bilinmeyen tablo) tek satırda birleşir.
export function mergeErrors(serverErrors) {
  const errors = {};
  for (const error of Array.isArray(serverErrors) ? serverErrors : []) {
    const field = text(error?.field);
    const message = text(error?.message).trim();
    if (!message) continue;
    const key = field || "";
    errors[key] = errors[key] ? `${errors[key]} ${message}` : message;
  }
  return errors;
}

function text(value) {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

function items(value) {
  return (Array.isArray(value) ? value : []).map((item) => text(item).trim()).filter(Boolean);
}

function commas(value) {
  return String(text(value)).split(",").map((part) => part.trim()).filter(Boolean);
}

function lines(value) {
  return String(text(value)).split(/\r?\n/).map((part) => part.trim()).filter(Boolean);
}
