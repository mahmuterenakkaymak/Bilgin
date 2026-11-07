// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { describe, expect, it } from "vitest";
import { STEPS, STEP_MS, stepAt } from "./steps.js";

describe("adım etiketleri", () => {
  it("dört adım R5-18 sırasıyla ve 1200 ms adımla ilerler", () => {
    expect(STEPS).toEqual(["Soru okunuyor", "Şema aranıyor", "SQL çalıştırılıyor", "Cevap yazılıyor"]);
    expect(STEP_MS).toBe(1200);
    expect(stepAt(0)).toBe(0);
    expect(stepAt(1199)).toBe(0);
    expect(stepAt(1200)).toBe(1);
    expect(stepAt(2400)).toBe(2);
    expect(stepAt(3600)).toBe(3);
  });

  it("son adımda durur, uzun soru dördüncü adımı geçmez", () => {
    expect(stepAt(3600 + 1200 * 40)).toBe(STEPS.length - 1);
  });

  it("geçersiz süre ilk adımı verir", () => {
    expect(stepAt(-5)).toBe(0);
    expect(stepAt(undefined)).toBe(0);
    expect(stepAt(Number.NaN)).toBe(0);
    expect(stepAt(Number.POSITIVE_INFINITY)).toBe(0);
  });
});
