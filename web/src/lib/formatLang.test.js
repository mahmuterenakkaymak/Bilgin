// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { describe, expect, it } from "vitest";
import { formatCell, formatCompact, formatDate, formatNumber, formatPercent } from "./format.js";
import { withFormatters } from "./chartFormat.js";
import { factValue } from "./facts.js";

// R8-16: aynı sayı arayüzün diliyle okunur. Türkçe taraf bugünkü okunuşunu korur; İngilizcede
// binlik virgül, ondalık nokta, yüzde sonda ve ölçek K/M/B'dir.

// 27 Ekim 2026 yerel saatle kurulur: UTC'ye çevirmek tarihi bir gün kaydırabilirdi.
const DAY = new Date(2026, 9, 27);

function barOption(format = "number") {
  return {
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: ["Ankara", "İzmir"] },
    yAxis: { type: "value" },
    series: [{ type: "bar", name: "Tutar", data: [1234.5, 99] }],
    bilgin: { value_format: format, value_column: "Tutar", label_column: "Sehir" },
  };
}

describe("İngilizce okunuş", () => {
  it("binlik ayıracı virgül, ondalık nokta", () => {
    expect(formatNumber(1234.56, "en")).toBe("1,234.56");
    expect(formatNumber(12345, "en")).toBe("12,345");
    expect(formatNumber(-2.5, "en")).toBe("-2.5");
    expect(formatCell(1234.56, "en")).toBe("1,234.56");
  });

  it("yüzde işaretinin yeri sonda", () => {
    expect(formatPercent(12.3, "en")).toBe("12.3%");
    expect(formatPercent(-1.5, "en")).toBe("-1.5%");
  });

  it("ölçek bitişik kısaltma", () => {
    expect(formatCompact(12500, "en")).toBe("12.5K");
    expect(formatCompact(1_500_000, "en")).toBe("1.5M");
    expect(formatCompact(999, "en")).toBe("999");
  });

  it("tarih ayın kısaltmasıyla ve virgülle", () => {
    expect(formatDate(DAY, "en")).toBe("Oct 27, 2026");
    expect(formatDate("2026-10-27T12:00:00", "en")).toBe("Oct 27, 2026");
  });

  it("yokluk iki dilde de çizgi", () => {
    expect(formatNumber(null, "en")).toBe("–");
    expect(formatPercent(undefined, "en")).toBe("–");
    expect(formatCompact("1234,5", "en")).toBe("–");
    expect(formatDate("", "en")).toBe("–");
  });
});

describe("Türkçe okunuş değişmedi", () => {
  const VALUES = [
    [1234.56, "1.234,56"],
    [12345, "12.345"],
    [1234.5, "1.234,5"],
    [-2.5, "-2,5"],
    [0, "0"],
  ];

  for (const [value, expected] of VALUES) {
    it(`formatNumber(${value}) == "${expected}"`, () => {
      expect(formatNumber(value)).toBe(expected);
      expect(formatNumber(value, "tr")).toBe(expected);
    });
  }

  it("yüzde, ölçek, tarih ve tanımadık dil Türkçe", () => {
    expect(formatPercent(12.3)).toBe("%12,3");
    expect(formatPercent(-1.5)).toBe("-%1,5");
    expect(formatCompact(12500)).toBe("12,5 bin");
    expect(formatDate(DAY)).toContain("2026");
    expect(formatDate(DAY)).not.toBe(formatDate(DAY, "en"));
    expect(formatNumber(1234.56, "de")).toBe("1.234,56");
  });
});

describe("grafik biçimleyicileri dil ile", () => {
  it("sayısal eksen etiketi arayüzün dilinde", () => {
    expect(withFormatters(barOption(), "en").yAxis.axisLabel.formatter(1234.56)).toBe("1,234.56");
    expect(withFormatters(barOption()).yAxis.axisLabel.formatter(1234.56)).toBe("1.234,56");
  });

  it("ipucu ve seri etiketi arayüzün dilinde", () => {
    expect(withFormatters(barOption(), "en").tooltip.formatter({ seriesName: "Tutar", value: 1234.5 })).toBe(
      "Tutar: 1,234.5",
    );
    expect(withFormatters(barOption("percent"), "en").tooltip.formatter({ seriesName: "Pay", value: 12.34 })).toBe(
      "Pay: 12.3%",
    );
    expect(withFormatters(barOption(), "en").series[0].label.formatter({ value: 1234.56 })).toBe("1,234.56");
  });
});

describe("olgular arayüzün diliyle", () => {
  const total = { name: "total", label: "Toplam", value: 8910, display: "8.910", percent: false };
  const mean = { name: "mean", label: "Ortalama", value: 1782.0, display: "1.782,00", percent: false };
  const share = { name: "top_share", label: "En yüksek pay", value: 27.8, display: "%27,8", percent: true };
  const item = { name: "top_item", label: "Öne çıkan", value: "Siyah Çay 500 g", display: "Siyah Çay 500 g" };

  it("cevabın dili ile arayüzün dili aynıysa sunucunun okunuşu olduğu gibi okunur", () => {
    expect(factValue(total, "tr", "tr")).toBe("8.910");
    expect(factValue(mean, "tr", "tr")).toBe("1.782,00");
    expect(factValue(share, "tr", "tr")).toBe("%27,8");
  });

  it("İngilizce arayüz Türkçe cevabın sayısını İngilizce yazar, basamağını düşürmez", () => {
    expect(factValue(total, "en", "tr")).toBe("8,910");
    expect(factValue(mean, "en", "tr")).toBe("1,782.00");
    expect(factValue(share, "en", "tr")).toBe("27.8%");
  });

  it("İngilizce cevabın sayısı Türkçe arayüzde Türkçe okunur", () => {
    expect(factValue({ ...total, display: "8,910" }, "tr", "en")).toBe("8.910");
    expect(factValue({ ...share, display: "27.8%", value: 27.8, percent: true }, "tr", "en")).toBe("%27,8");
  });

  it("sayı olmayan olgu ve okunuşu olmayan olgu kendi halinde", () => {
    expect(factValue(item, "en", "tr")).toBe("Siyah Çay 500 g");
    expect(factValue(null, "en", "tr")).toBe("");
    expect(factValue({ value: 1 }, "en", "tr")).toBe("");
  });
});
