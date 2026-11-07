// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import answered from "../fixtures/answered.json";
import clarification from "../fixtures/clarification.json";
import ChartView from "./ChartView.jsx";
import ClarificationCard from "./ClarificationCard.jsx";

const noop = () => {};

// Cümlelerdeki kesme işareti ve tırnak SSR çıktısında düz karakter değildir; okunur metin öyle aranır.
function render(node) {
  return renderToStaticMarkup(node)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&");
}

// report/chart.chart_spec'in çıktısı: işlevi olmayan düz ECharts JSON'u + `bilgin` ipucu (R5-6).
const SPEC = {
  type: "bar",
  option: {
    tooltip: { trigger: "axis" },
    grid: { left: 8, right: 16, top: 16, bottom: 8 },
    xAxis: { type: "category", data: ["Siyah Çay 500 g", "Buğday Unu 500 g"] },
    yAxis: { type: "value" },
    series: [{ type: "bar", data: [2480, 2140] }],
    bilgin: { value_format: "number", value_column: "SATIS_MIKTARI", label_column: "URUN_ADI" },
  },
};

describe("ChartView", () => {
  it("grafiği olmayan cevapta yer de açılmaz", () => {
    expect(render(<ChartView chart={null} />)).toBe("");
    expect(render(<ChartView />)).toBe("");
    // tür var ama seçeneği yok: çizilecek bir şey yoktur, kutu kurulmaz.
    expect(render(<ChartView chart={{ type: "bar" }} />)).toBe("");
  });

  it("seçenek geldiğinde grafik kutusu kurulur", () => {
    const html = render(<ChartView chart={SPEC} />);
    expect(html).toContain('id="chart"');
    expect(html).toContain('class="chart"');
  });
});

describe("ClarificationCard", () => {
  it("başlık, soru ve her seçenek kendi sırasıyla düğme", () => {
    const html = render(<ClarificationCard payload={clarification} onChoose={noop} onChange={noop} />);
    expect(html).toContain('id="clarification-card"');
    expect(html).toContain(">Netleştirelim</h2>");
    expect(html).toContain("'satış' ile neyi kastediyorsunuz?");
    expect(html).toContain('id="clarification-change"');
    expect(html).toContain(">Soruyu değiştir</button>");
  });

  it("seçenekler sıfırdan numaralanır ve metni düğmede okunur", () => {
    const html = render(<ClarificationCard payload={clarification} onChoose={noop} onChange={noop} />);
    const indexes = [...html.matchAll(/data-option-index="(\d+)"/g)].map((match) => match[1]);
    expect(indexes).toEqual(["0", "1", "2"]);
    for (const [index, option] of clarification.clarification.options.entries()) {
      expect(html).toContain(`data-option-index="${index}"`);
      expect(html).toContain(`>${option}</button>`);
    }
  });

  it("seçenekleri eksik netleştirme çökmez, soru ve değiştirme yolu kalır", () => {
    const partial = { clarification: { question: "Hangisini kastettin?" } };
    const html = render(<ClarificationCard payload={partial} onChoose={noop} onChange={noop} />);
    expect(html).toContain(">Hangisini kastettin?</p>");
    expect(html).not.toContain("data-option-index");
    expect(html).toContain(">Soruyu değiştir</button>");
    expect(render(<ClarificationCard onChoose={noop} onChange={noop} />)).toContain(">Netleştirelim</h2>");
  });
});

describe("netleştirme örneği", () => {
  it("her durumda taşınan AskPayload anahtar kümesini korur", () => {
    expect(Object.keys(clarification).sort()).toEqual(Object.keys(answered).sort());
    expect(clarification.status).toBe("needs_clarification");
    expect(clarification.clarification.options.length).toBeGreaterThanOrEqual(2);
  });
});
