// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// Tema üç durumludur (T222): "system" tarayıcının/sistemin tercihine bırakır ve kök niteliği
// kaldırılır; "dark" ve "light" hangi token kümesinin geçerli olduğunu `html[data-theme]` ile
// sabitler. Değer tek bir anahtarda durur, arayüzün geri kalanı onu okumaz.
export const THEMES = ["system", "dark", "light"];

const STORAGE_KEY = "bilgin-theme";

export function nextTheme(value) {
  return THEMES[(THEMES.indexOf(value) + 1) % THEMES.length];
}

// Depolama ya hiç yok (Node'daki testler, kapalı özel mod) ya da okumada patlarsa "system":
// yanlışı okumaktansa sisteminle devam etmek daha iyi.
export function readStored(storage) {
  try {
    const value = storage?.getItem(STORAGE_KEY);
    return THEMES.includes(value) ? value : "system";
  } catch {
    return "system";
  }
}

export function store(storage, value) {
  try {
    storage?.setItem(STORAGE_KEY, value);
  } catch {
    // Depolama yazmayı reddederse tema yine bu sayfada geçerlidir; yalnızca kalıcı olmaz.
  }
}

export function applyTheme(doc, value) {
  const root = doc?.documentElement;
  if (!root) return;
  if (value === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", value);
}
