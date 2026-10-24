// Kural formunun iki yüzü arasında çeviri: API kaydı (listeler) <-> form (tek satır metinler).
// Zorunlu alan mesajları sunucudakiyle (schema_map/rules_edit.py) birebir aynı yazılır ki
// kullanıcı boş formu göndermek için bir gidiş-gerişi beklemesin (R5-18).

const ID_PATTERN = /^[a-z0-9_]+$/;

export const ID_MESSAGE = "Kimlik yalnız küçük harf, rakam ve alt çizgiden oluşmalı (ör. net_satis).";
export const TERM_MESSAGE = "Terim boş olamaz.";
export const DEFINITION_MESSAGE = "Tanım boş olamaz.";

export function toForm(rule) {
  const item = rule ?? {};
  return {
    id: text(item.id),
    term: text(item.term),
    synonyms: items(item.synonyms).join(", "),
    definition: text(item.definition),
    sql_hint: text(item.sql_hint),
    tables: items(item.tables).join(", "),
    // ASSUMPTION: işaretçiler formda satır başına bir düzenli ifade — virgülle ayrılsa `\\d{1,3}` bölünür.
    markers: items(item.markers).join("\n"),
  };
}

export function fromForm(form) {
  const item = form ?? {};
  return {
    id: text(item.id).trim(),
    term: text(item.term).trim(),
    synonyms: commas(item.synonyms),
    definition: text(item.definition).trim(),
    sql_hint: text(item.sql_hint).trim(),
    tables: commas(item.tables),
    markers: lines(item.markers),
  };
}

export function clientErrors(form) {
  const item = form ?? {};
  const errors = {};
  if (!ID_PATTERN.test(text(item.id).trim())) errors.id = ID_MESSAGE;
  if (!text(item.term).trim()) errors.term = TERM_MESSAGE;
  if (!text(item.definition).trim()) errors.definition = DEFINITION_MESSAGE;
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
