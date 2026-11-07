// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// Arayüz dili temanın yanında kendi anahtarında durur: tema üç durumlu, dil iki dilli, ve
// R8-15/R8-16 anahtarın adını sabitliyor. Okuma da yazma da sessizce düşer: Node'daki testlerde
// `localStorage` hiç yoktur, kapalı özel modda da yazma reddedilir; dil o durumda yalnız
// içinde bulunulan sayfada geçerlidir.
export const LANG_KEY = "bilgin.lang";

export function readLang() {
  try {
    return localStorage.getItem(LANG_KEY);
  } catch {
    return null;
  }
}

export function storeLang(lang) {
  try {
    localStorage.setItem(LANG_KEY, lang);
  } catch {
    // Kalıcı olamayan tercih bu oturumda yine geçerlidir.
  }
}
