// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { describe, expect, it } from "vitest";
import { formatCell, formatNumber, formatPercent, formatSeconds, isNumericColumn } from "./format.js";

describe("formatNumber", () => {
  it("binlik ayıracı nokta, ondalık virgül", () => {
    expect(formatNumber(1234.56)).toBe("1.234,56");
    expect(formatNumber(12345)).toBe("12.345");
    expect(formatNumber(1234.5)).toBe("1.234,5");
    expect(formatNumber(-2.5)).toBe("-2,5");
    expect(formatNumber(0)).toBe("0");
  });

  it("sayı olmayan yokluk olarak yazılır", () => {
    expect(formatNumber(null)).toBe("–");
    expect(formatNumber(undefined)).toBe("–");
    expect(formatNumber(Number.NaN)).toBe("–");
    expect(formatNumber("1234,5")).toBe("–");
  });
});

describe("formatPercent", () => {
  it("imleç sayının önünde, tek basamak", () => {
    expect(formatPercent(12.3)).toBe("%12,3");
    expect(formatPercent(12.34)).toBe("%12,3");
    expect(formatPercent(0)).toBe("%0,0");
    expect(formatPercent(100)).toBe("%100,0");
    expect(formatPercent(-1.5)).toBe("-%1,5");
    expect(formatPercent(null)).toBe("–");
  });
});

describe("formatCell", () => {
  it("sayı Türkçe, boş hücre çizgi, metin olduğu gibi", () => {
    expect(formatCell(1234.56)).toBe("1.234,56");
    expect(formatCell(null)).toBe("–");
    expect(formatCell(undefined)).toBe("–");
    expect(formatCell("Ankara")).toBe("Ankara");
    expect(formatCell("0042")).toBe("0042");
  });
});

describe("isNumericColumn", () => {
  const rows = [
    ["Ankara", 1234.5, null],
    ["İzmir", 99, null],
  ];

  it("tamamı sayı olan sütun sayıdır", () => {
    expect(isNumericColumn(rows, 1)).toBe(true);
  });

  it("tek metin hücre sütunu metin yapar", () => {
    expect(isNumericColumn(rows, 0)).toBe(false);
    expect(isNumericColumn([[1], ["2"]], 0)).toBe(false);
  });

  it("hepsi boş ya da satır yoksa sayı değildir", () => {
    expect(isNumericColumn(rows, 2)).toBe(false);
    expect(isNumericColumn([], 0)).toBe(false);
    expect(isNumericColumn(null, 0)).toBe(false);
    expect(isNumericColumn([[Number.NaN]], 0)).toBe(false);
  });
});

describe("formatSeconds", () => {
  it("saniye, dakika ve saat Türkçe okunur", () => {
    expect(formatSeconds(0.4)).toBe("0,4 sn");
    expect(formatSeconds(12.34)).toBe("12,3 sn");
    expect(formatSeconds(65)).toBe("1 dk 5 sn");
    expect(formatSeconds(120)).toBe("2 dk");
    expect(formatSeconds(3725)).toBe("1 sa 2 dk");
    expect(formatSeconds(3600)).toBe("1 sa");
  });

  it("bilinmeyen süre hiçbir şey yazılmaz", () => {
    expect(formatSeconds(null)).toBe("");
    expect(formatSeconds(undefined)).toBe("");
    expect(formatSeconds(-1)).toBe("");
    expect(formatSeconds(Number.NaN)).toBe("");
  });
});
