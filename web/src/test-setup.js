// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// R8-15: provider sarmalamayan her test bugünkü Türkçe çıktıyı görmeye devam etsin diye
// iki katalog da her test dosyasından önce kayıtlı gelir.
import en from "./i18n/en.json";
import tr from "./i18n/tr.json";
import { registerCatalog } from "./i18n/index.js";

registerCatalog("tr", tr);
registerCatalog("en", en);
