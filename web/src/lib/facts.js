// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// Kartın çip şeridi: olguların tamamı değil, cevabın üç özeti. Okunur okunuşu olmayan olgu çip
// olmaz; tek hücrelik cevapta üç olgu aynı sayıyı söyler, şeritte bir kez okunur. Dönen öğeler
// girdi dizisinin kendi referanslarıdır — kanıt paneli "çipte olmayanlar"ı bu kimlikle ayırır.
import { formatNumber, formatPercent, normalizeLang } from "./format.js";

const CHIP_FACTS = ["total", "max", "mean"];

export function chipFacts(facts) {
  const readable = (Array.isArray(facts) ? facts : []).filter((fact) => fact?.label && fact?.display);
  const picked = [];
  for (const name of CHIP_FACTS) {
    const fact = readable.find((item) => item.name === name);
    if (fact && !picked.some((item) => item.display === fact.display)) picked.push(fact);
  }
  return picked;
}

// Olgunun okunuşu sunucuda cevabın diliyle yazılmıştır (R8-3); arayüz dili farklıysa sayı arayüz
// diliyle yeniden okunur. Basamak sayısı sunucunun yazısından alınır, hiçbir değer yeniden
// hesaplanmaz; sayı olmayan olgu (metin) kendi okunuşunda kalır.
export function factValue(fact, lang = "tr", answerLang = "tr") {
  const display = typeof fact?.display === "string" ? fact.display : "";
  const value = fact?.value;
  if (normalizeLang(lang) === normalizeLang(answerLang)) return display;
  if (!display || typeof value !== "number" || !Number.isFinite(value)) return display;
  const decimals = fractionDigits(display, answerLang);
  return fact.percent ? formatPercent(value, lang, decimals) : formatNumber(value, lang, decimals);
}

// Sunucunun yazdığı ondalık basamak: tr "1.782,00" → 2, "8.910" → 0; en "27.8%" → 1.
function fractionDigits(text, answerLang) {
  const mark = normalizeLang(answerLang) === "en" ? "." : ",";
  const match = new RegExp(`\\${mark}(\\d+)`).exec(text);
  return match ? match[1].length : 0;
}
