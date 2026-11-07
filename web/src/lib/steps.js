// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// Yükleme adımlarının tek kaynağı (R5-18): sunucudan olay gelmez, etiket geçen süreye göre ilerler
// ve son adımda durur — uzun bir soru ekranda "bitti" numarası yapmaz.
export const STEPS = ["Soru okunuyor", "Şema aranıyor", "SQL çalıştırılıyor", "Cevap yazılıyor"];
export const STEP_MS = 1200;

export function stepAt(elapsedMs) {
  const ms = Number(elapsedMs);
  if (!Number.isFinite(ms) || ms <= 0) return 0;
  return Math.min(Math.floor(ms / STEP_MS), STEPS.length - 1);
}
