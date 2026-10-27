// Harita ekranının akışı (R6-19): tek durum ağacının indirgeyicisi. Ağ çağrıları burada değildir —
// bileşen api'yi çağırıp sonucu eylem olarak getirir, böylece akış sahte zamanlayıcı olmadan test edilir.

export const NO_FILE_MESSAGE = "Önce doldurduğunuz şablonu seçin.";
export const FAIL_MESSAGE = "İşlem tamamlanamadı.";
export const INDEX_MESSAGE = "İndeks kurulamadı.";
export const SWITCH_MESSAGE = "Veri kümesine geçilemedi.";

// Cümlelerin ekranı kataloğunda (R8-20): indirgeyicinin dili yok, o yüzden hâlde Türkçeleri durur
// — mapFlow.test.js onları bu haliyle dondurmuştur. Ekran bir cümleyi bu kayıtta arar: bulunursa
// kendi dilinin anahtarından, bulunamazsa sunucunun cümlesi olduğu gibi yazılır.
export const MESSAGE_KEYS = new Map([
  [FAIL_MESSAGE, "map.failed"],
  [INDEX_MESSAGE, "map.indexFailed"],
  [SWITCH_MESSAGE, "map.switchFailed"],
]);

// Sözleşme "apply / status"un üç aşaması; başarısızlıkta ekran adımlar yerine cümleyi gösterir.
// Adımların yazısı kataloğun anahtarlarıdır; PROGRESS_STEPS adım sayısının ve Türkçe yazının
// kaydıdır — mapFlow.test.js onu bu haliyle dondurmuştur.
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
      return { ...state, status: "noFile", error: { kind: "nofile", message: NO_FILE_MESSAGE } };
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
        error: status === "failed" ? { kind: "index", message: text(job.message) || INDEX_MESSAGE } : null,
      };
    }
    case "fail":
      return {
        ...state,
        status: "failed",
        error: { kind: text(action.kind) || "failed", message: text(action.message) || FAIL_MESSAGE },
      };
    case "activated":
      return { ...state, status: "activated", activated: text(action.name) || text(state.job?.name) };
    case "switchError":
      return {
        ...state,
        status: "switchError",
        error: { kind: "switch", message: text(action.message) || SWITCH_MESSAGE },
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

export function progressSteps(phase) {
  const current = PHASE_STEP[phase] ?? -1;
  return PROGRESS_STEPS.map((label, index) => ({
    label,
    done: index < current || phase === "done",
    active: index === current && phase !== "done",
  }));
}

function text(value) {
  return typeof value === "string" ? value.trim() : "";
}
