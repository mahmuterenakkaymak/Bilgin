import { describe, expect, it } from "vitest";
import { withFormatters } from "./chartFormat.js";

function barOption(format = "number") {
  return {
    tooltip: { trigger: "axis" },
    grid: { left: 8 },
    xAxis: { type: "category", data: ["Ankara", "İzmir"] },
    yAxis: { type: "value" },
    series: [{ type: "bar", name: "Tutar", data: [1234.5, 99] }],
    bilgin: { value_format: format, value_column: "Tutar", label_column: "Sehir" },
  };
}

function pieOption(format = "number") {
  return {
    tooltip: { trigger: "item" },
    series: [{ type: "pie", name: "Tutar", data: [{ name: "Ankara", value: 12.34 }] }],
    bilgin: { value_format: format, value_column: "Tutar", label_column: "Sehir" },
  };
}

describe("withFormatters tooltip", () => {
  it("eksen ipucu değeri Türkçe yazar", () => {
    const formatter = withFormatters(barOption()).tooltip.formatter;
    expect(
      formatter([
        { axisValueLabel: "Ankara", marker: "●", seriesName: "Tutar", value: 1234.5 },
        { axisValueLabel: "Ankara", marker: "◦", seriesName: "Adet", value: 3 },
      ])
    ).toBe("Ankara<br/>●Tutar: 1.234,5<br/>◦Adet: 3");
  });

  it("oran biçimi imleci öne alır", () => {
    const formatter = withFormatters(barOption("percent")).tooltip.formatter;
    expect(formatter([{ axisValueLabel: "Ankara", seriesName: "Pay", value: 12.34 }])).toBe("Ankara<br/>Pay: %12,3");
  });

  it("tekil ipucu pasta dilinin adını gösterir", () => {
    const formatter = withFormatters(pieOption("percent")).tooltip.formatter;
    expect(formatter({ name: "Ankara", seriesName: "Tutar", marker: "●", value: 12.34 })).toBe("●Ankara: %12,3");
  });

  it("saçılım noktasının iki değeri de biçimlenir, yokluk çizgidir", () => {
    const option = withFormatters({
      tooltip: { trigger: "item" },
      xAxis: { type: "value" },
      yAxis: { type: "value" },
      series: [{ type: "scatter", name: "Sepet", data: [[1234.5, 0.5]] }],
      bilgin: { value_format: "number" },
    });
    expect(option.tooltip.formatter({ seriesName: "Sepet", value: [1234.5, 0.5] })).toBe("Sepet: 1.234,5, 0,5");
    expect(option.tooltip.formatter({ seriesName: "Sepet", value: null })).toBe("Sepet: –");
  });
});

describe("withFormatters eksen ve etiket", () => {
  it("yalnız sayısal eksen biçimlenir, kategori eksenine dokunulmaz", () => {
    const next = withFormatters(barOption());
    expect(next.yAxis.axisLabel.formatter(1234.56)).toBe("1.234,56");
    expect(next.yAxis.type).toBe("value");
    expect(next.xAxis.axisLabel).toBeUndefined();
  });

  it("mevcut eksen ayarları korunur", () => {
    const option = barOption();
    option.yAxis.axisLabel = { rotate: 30 };
    const next = withFormatters(option);
    expect(next.yAxis.axisLabel.rotate).toBe(30);
    expect(typeof next.yAxis.axisLabel.formatter).toBe("function");
  });

  it("etiket adı koruyarak Türkçe sayı yazar", () => {
    const next = withFormatters(pieOption());
    expect(next.series[0].label.formatter({ name: "Ankara", value: 1234.5 })).toBe("Ankara: 1.234,5");
    expect(withFormatters(barOption()).series[0].label.formatter({ value: 99 })).toBe("99");
  });
});

describe("withFormatters başlık ve eksen adı", () => {
  it("ölçünün adı option'da bir kez durur: başlıkta, eksen adı uydurulmaz", () => {
    const next = withFormatters(barOption());
    expect(next.title.text).toBe("Tutar");
    expect(next.yAxis.name).toBeUndefined();
    expect(next.xAxis.name).toBeUndefined();
  });

  it("altyazılı ERP kolon adı Türkçe okunuşuna döner", () => {
    const option = barOption();
    option.bilgin.value_column = "SATIS_ADEDI";
    const next = withFormatters(option);
    expect(next.title.text).toBe("Satis adedi");
    expect(next.yAxis.name).toBeUndefined();
  });

  it("başlığı ve eksen adı hazır seçeneğe dokunulmaz, biçimleyiciler yine eklenir", () => {
    const option = barOption();
    option.title = { text: "Eylül 2026 satışı", left: "center" };
    option.yAxis.name = "Tutar (TL)";
    const next = withFormatters(option);
    expect(next.title).toEqual({ text: "Eylül 2026 satışı", left: "center" });
    expect(next.yAxis.name).toBe("Tutar (TL)");
    expect(typeof next.yAxis.axisLabel.formatter).toBe("function");
  });

  it("pasta grafiğinde başlık vardır, eksen adı uydurulmaz", () => {
    const next = withFormatters(pieOption());
    expect(next.title.text).toBe("Tutar");
    expect(next.yAxis).toBeUndefined();
  });

  it("ölçü kolonu yoksa başlık uydurulmaz ve kaynak seçenek olduğu gibi kalır", () => {
    const bare = withFormatters({
      tooltip: { trigger: "item" },
      series: [{ type: "bar", data: [1] }],
      bilgin: { value_format: "number" },
    });
    expect(bare.title).toBeUndefined();

    const option = barOption();
    expect(withFormatters(option).title.text).toBe("Tutar");
    expect(option.title).toBeUndefined();
    expect(option.yAxis.name).toBeUndefined();
  });
});

describe("withFormatters veriyi değiştirmez", () => {
  it("veri, seri tipi ve bilgin bloğu aynı kalır; kaynak seçenek olduğu gibi durur", () => {
    const option = barOption();
    const next = withFormatters(option);
    expect(next.series[0].data).toBe(option.series[0].data);
    expect(next.series[0].type).toBe("bar");
    expect(next.xAxis.data).toBe(option.xAxis.data);
    expect(next.bilgin).toEqual(option.bilgin);
    expect(next.grid).toBe(option.grid);
    expect(option.tooltip.formatter).toBeUndefined();
    expect(option.yAxis.axisLabel).toBeUndefined();
    expect(option.series[0].label).toBeUndefined();
  });

  it("bilgin yoksa sayı biçimi varsayılır, boş seçenek olduğu gibi döner", () => {
    const option = { tooltip: { trigger: "item" }, series: [{ type: "bar", data: [1234.5] }] };
    expect(withFormatters(option).tooltip.formatter({ value: 1234.5 })).toBe("1.234,5");
    expect(withFormatters(null)).toBeNull();
  });
});
