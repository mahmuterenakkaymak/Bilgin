// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import Root from "./Root.jsx";
import { I18nProvider, loadCatalog, pickLang } from "./i18n/index.js";
import { readLang } from "./lib/lang.js";
import { applyTheme, readStored } from "./lib/theme.js";
import "./styles.css";

// Koyu teması seçili olan ilk boyamayı açık görmesin: kök nitelik React render olmadan önce yazılır.
try {
  applyTheme(document, readStored(localStorage));
} catch {
  // Depolama erişilemiyorsa açılış zaten sistem temasındadır.
}

// Dil katalog inmeden çözülmeli: çevirisi yüklenmemiş bir ağaç cümle yerine anahtar gösterirdi.
// `me` burada henüz okunmadı — kapının (Root) getirdiği kişinin kayıtlı dili App üzerinden
// uygulanır, o yüzden sıra yerel tercih → tarayıcı → tr.
const lang = pickLang({ stored: readLang(), navigator: window.navigator });

loadCatalog(lang).then((code) => {
  document.documentElement.lang = code;
  createRoot(document.getElementById("root")).render(
    <StrictMode>
      <I18nProvider lang={code}>
        <Root />
      </I18nProvider>
    </StrictMode>,
  );
});
