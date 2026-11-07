// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// Harita ekranının akışı (R6-19): tek durum ağacının indirgeyicisi. Ağ çağrıları burada değildir —
// bileşen api'yi çağırıp sonucu eylem olarak getirir, böylece akış sahte zamanlayıcı olmadan test edilir.

import { makeT } from "../i18n/index.js";

// İndirgeyicinin dili yok: kendi cümlesi hâlde her zaman kataloğun Türkçesiyle durur (R8-18), ekran
// onu `t()`den geçirir — t() tanımadığı cümleyi olduğu gibi bıraktığı için sunucunun cümlesi de aynı
// yoldan geçer. mapFlow.test.js bu cümleleri Türkçe değerleriyle dondurmuştur; katalog onlardan
// saparsa test kırılır.
const tTr = makeT("tr");

export const NO_FILE_MESSAGE = "Önce doldurduğunuz şablonu seçin.";
export const INDEX_MESSAGE = "İndeks kurulamadı.";

// Sözleşme "apply / status"un üç aşaması; başarısızlıkta ekran adımlar yerine cümleyi gösterir.
// Adımların yazısı kataloğun anahtarlarıdır; PROGRESS_STEPS adım sayısının ve Türkçe yazının
// kaydıdır — mapFlow.test.js onu bu haliyle dondurmuştur, arayüz progressFlags'i okur.
export const PROGRESS_STEPS = ["Yazılıyor", "İndeks kuruluyor", "Hazır"];
export const PROGRESS_STEP_KEYS = ["map.step.writing", "map.step.indexing", "map.step.done"];
const PHASE_STEP = { writing: 0, indexing: 1, done: 2 };
const PHASE_STATUS = { writing: "applying", indexing: "indexing", done: "done", failed: "failed" };

export const initialMapState = {
  status: "idle", // idle | noFile | previewing | previewed | applying | indexing | done | failed | activated | switchError
  filename: "",
  preview: null, // preview response: {preview_id, dataset, counts, errors, warnings, db_check}
  job: null, // apply / status: {preview_id, name, phase, message}
  error: null, // {kind, message}; noFile, failed ve switchError'da okunur
  activated: "", // "activated" durumunda geçilen kümenin adı
};

export function mapReducer(state = initialMapState, action = {}) {
  switch (action.type) {
    case "select":
      // Yeni dosya eski raporu geçersiz kılar: sayılar yüklenen dosyaya aittir.
      return { ...initialMapState, filename: text(action.filename) };
    case "nofile":
      return { ...state, status: "noFile", error: { kind: "nofile", message: tTr("map.nofile") } };
    case "preview":
      if (!state.filename) return mapReducer(state, { type: "nofile" });
      return { ...state, status: "previewing", preview: null, job: null, error: null };
    case "previewed":
      return { ...state, status: "previewed", preview: action.preview ?? null, job: null, error: null };
    case "apply":
      return canApply(state) ? { ...state, status: "applying", error: null } : state;
    case "job": {
      const job = action.job ?? null;
      const status = PHASE_STATUS[job?.phase];
      if (!status) return state; // beklenmedik aşama: ekranda yazılmış cümlenin üstüne yazılmaz
      return {
        ...state,
        status,
        job,
        error: status === "failed" ? { kind: "index", message: text(job.message) || tTr("map.indexFailed") } : null,
      };
    }
    case "fail":
      return {
        ...state,
        status: "failed",
        error: { kind: text(action.kind) || "failed", message: text(action.message) || tTr("map.failed") },
      };
    case "activated":
      return { ...state, status: "activated", activated: text(action.name) || text(state.job?.name) };
    case "switchError":
      return {
        ...state,
        status: "switchError",
        error: { kind: "switch", message: text(action.message) || tTr("map.switchFailed") },
      };
    case "reset":
      return { ...initialMapState };
    default:
      return state;
  }
}

// "Oluştur" düğmesi yalnız okunmuş rapor hatalıysa kapalıdır; hata cümlesi ekranda zaten duruyor.
export function canApply(state) {
  if (state?.status !== "previewed") return false;
  return !(Array.isArray(state.preview?.errors) && state.preview.errors.length > 0);
}

// Yoklama yalnız iş sürerken: done ve failed'da zamanlayıcı durur, aksi hâlde ekran sonsuza yoklar.
export function shouldPoll(state) {
  return state?.status === "applying" || state?.status === "indexing";
}

// Adım bandının hâli: ekran yazıyı PROGRESS_STEP_KEYS'in kendi satırından okur, burada yalnız
// sırası ve yanıp sönmesi duruyor.
export function progressFlags(phase) {
  const current = PHASE_STEP[phase] ?? -1;
  return PROGRESS_STEP_KEYS.map((_, index) => ({
    done: index < current || phase === "done",
    active: index === current && phase !== "done",
  }));
}

// mapFlow.test.js adım adlarını Türkçeleriyle dondurmuştur; arayüz progressFlags'i okur.
export function progressSteps(phase) {
  return progressFlags(phase).map((step, index) => ({ label: tTr(PROGRESS_STEP_KEYS[index]), ...step }));
}

function text(value) {
  return typeof value === "string" ? value.trim() : "";
}
