// Yükleme adımlarının tek kaynağı (R5-18): sunucudan olay gelmez, etiket geçen süreye göre ilerler
// ve son adımda durur — uzun bir soru ekranda "bitti" numarası yapmaz.
// Ekrana yazılan şey STEP_KEYS'in katalog satırıdır (R8-18); STEPS adım sayısının ve Türkçe yazının
// kaydıdır — steps.test.js onu bu haliyle dondurmuştur, arayüz onu okumaz.
export const STEPS = ["Soru okunuyor", "Şema aranıyor", "SQL çalıştırılıyor", "Cevap yazılıyor"];
export const STEP_KEYS = ["step.read", "step.schema", "step.sql", "step.answer"];
export const STEP_MS = 1200;

export function stepAt(elapsedMs) {
  const ms = Number(elapsedMs);
  if (!Number.isFinite(ms) || ms <= 0) return 0;
  return Math.min(Math.floor(ms / STEP_MS), STEP_KEYS.length - 1);
}
