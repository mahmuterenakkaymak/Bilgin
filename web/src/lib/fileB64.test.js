// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { describe, expect, it } from "vitest";
import { arrayBufferToBase64, isXlsxName } from "./fileB64.js";

// Ölçüt Node'un kendi kodlayıcısı: elle yazılmış bir beklenen dizi yerine byte-for-byte karşılaştırma.
function expected(bytes) {
  return Buffer.from(bytes).toString("base64");
}

function randomBytes(length) {
  const bytes = new Uint8Array(length);
  for (let i = 0; i < length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  return bytes;
}

describe("arrayBufferToBase64", () => {
  it("boşta ve her dolgu durumunda Buffer ile aynı metni verir", () => {
    for (const length of [0, 1, 2, 3, 4, 5]) {
      const bytes = randomBytes(length);
      expect(arrayBufferToBase64(bytes)).toBe(expected(bytes));
    }
  });

  it("64 KB'ı aşan yüklemede dilim sınırı base64'u bozmaz", () => {
    // Dilim 0x8000 = 32768 bayt: tam sınırı, bir fazlası ve iki katı denenir — sınırda bölünen
    // üçlü öbekler yanlışsa sonuç yalnız burada bozulur.
    for (const length of [32768, 32769, 65536, 100000]) {
      const bytes = randomBytes(length);
      expect(arrayBufferToBase64(bytes)).toBe(expected(bytes));
    }
  });

  it("ArrayBuffer ile onun görünümü aynı metni verir", () => {
    const bytes = randomBytes(1000);
    expect(arrayBufferToBase64(bytes.buffer)).toBe(arrayBufferToBase64(bytes));
    expect(arrayBufferToBase64(bytes.buffer)).toBe(expected(bytes));
  });

  it("Türkçe karakterli bir dosya baytları olduğu gibi taşınır", () => {
    const bytes = new TextEncoder().encode("bilgin-veritabani-şablonu.xlsx");
    expect(arrayBufferToBase64(bytes)).toBe(expected(bytes));
  });
});

describe("isXlsxName", () => {
  it("yalnız .xlsx ile biten ad doğru", () => {
    for (const name of ["harita.xlsx", "Bilgin Harita.XLSX", "  harita.xlsx  ", "a.b.xlsx"]) {
      expect(isXlsxName(name)).toBe(true);
    }
  });

  it("başka uzantı, çıplak uzantı ve boşluk yanlış", () => {
    for (const name of ["harita.xls", "harita.xlsm", "harita.xlsx.txt", "xlsx", ".xlsx", "", "   ", null, undefined, 3]) {
      expect(isXlsxName(name)).toBe(false);
    }
  });
});
