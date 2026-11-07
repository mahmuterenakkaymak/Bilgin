// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// R8-15: çevirinin tek kaynağı yanındaki JSON katalogları. Provider'ı olmayan her ağaç
// Türkçe kalır, böylece henüz taşınmamış hiçbir ekran ekranda boşluk göstermez.
import { createContext, createElement, useContext, useMemo, useState } from "react";

export const SUPPORTED = ["tr", "en"];
const FALLBACK = "tr";

const catalogs = { tr: {}, en: {} };

const normalize = (value) => (SUPPORTED.includes(value) ? value : FALLBACK);

export function registerCatalog(lang, catalog) {
  catalogs[lang] = catalog ?? {};
}

// Boş katalog "henüz inmedi" demektir: içi boş bir dille boyamak cümle yerine anahtar gösterir.
const hasCatalog = (code) => Object.keys(catalogs[code] ?? {}).length > 0;

// İki ayrı sabit import: vite her kataloğu kendi chunk'ına yazar (R8-18 bundle taraması).
export async function loadCatalog(lang) {
  const code = normalize(lang);
  const module = code === "en" ? await import("./en.json") : await import("./tr.json");
  registerCatalog(code, module.default ?? module);
  return code;
}

function interpolate(text, params) {
  if (!params) return text;
  return text.replace(/\{(\w+)\}/g, (match, name) => (name in params ? String(params[name]) : match));
}

// Bileşen olmayan saf işlevler (başlığın sağlık noktası, veritabanı ipucu) çeviriyi hook
// olmadan da okusun: dilin kendisi onlara parametre olarak geliyor, varsayılanı tr.
export function makeT(lang) {
  const code = normalize(lang);
  return (key, params) => {
    const text = catalogs[code]?.[key] ?? catalogs[FALLBACK]?.[key] ?? key;
    return interpolate(text, params);
  };
}

// Provider'sız kullanımın dili tr: testler ve henüz dil çözülmemiş ilk boyama bu değeri görür.
const fallbackContext = { lang: FALLBACK, t: makeT(FALLBACK), setLang: () => {} };
const I18nContext = createContext(fallbackContext);

export function I18nProvider({ lang, children }) {
  // Kullanıcı kendi dilini seçince prop'un (ör. giriş öncesi çözülen) değeri geri gelmesin;
  // henüz seçim yoksa prop izlenir, böylece giriş sonrası me.lang de uygulanır.
  const [chosen, setChosen] = useState(null);
  const current = chosen ?? normalize(lang);
  // Dil, kataloğu geldiği an değişir: düğme de me.lang de aynı yoldan geçer (açılışın kendi
  // indirmesi main.jsx'te). Katalogu inmemiş dile boyamak cümle yerine anahtar taşırdı, o yüzden
  // indirme bitene kadar ekranda eski dil durur; reddedilen indirme de eski dilde bırakır.
  const value = useMemo(
    () => ({
      lang: current,
      t: makeT(current),
      setLang: (code) => {
        const next = normalize(code);
        if (hasCatalog(next)) setChosen(next);
        else loadCatalog(next).then(() => setChosen(next), () => {});
      },
    }),
    [current],
  );
  return createElement(I18nContext.Provider, { value }, children);
}

export function useT() {
  return useContext(I18nContext);
}

function supportedTag(value) {
  if (typeof value !== "string") return null;
  const tag = value.trim().toLowerCase().split("-")[0];
  return SUPPORTED.includes(tag) ? tag : null;
}

// ASSUMPTION: "me" API'nin döndürdüğü kullanıcı nesnesi (me.lang); dil kodu da verilebilir.
export function pickLang({ me, stored, navigator: nav } = {}) {
  const candidates = [typeof me === "string" ? me : me?.lang, stored, nav?.language];
  for (const value of candidates) {
    const code = supportedTag(value);
    if (code) return code;
  }
  return FALLBACK;
}
