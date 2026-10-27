import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import answered from "../fixtures/answered.json";
import AnswerCard from "./AnswerCard.jsx";

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

function card(payload) {
  return render(<AnswerCard payload={payload} onSave={noop} />);
}

// Dört olgu: satır sayısı kartın özeti değildir, öteki üçü çip olur.
const FOUR = answered.facts.filter((fact) => ["row_count", "total", "max", "mean"].includes(fact.name));

function chipRow(html) {
  const start = html.indexOf('id="answer-facts"');
  expect(start).toBeGreaterThan(-1);
  return html.slice(start, html.indexOf("</ul>", start));
}

function panel(html) {
  const start = html.indexOf('id="evidence"');
  expect(start).toBeGreaterThan(-1);
  return html.slice(start);
}

describe("AnswerCard olgu çipleri", () => {
  it("dört olgunun üçü tablonun üstünde çip olarak okunur", () => {
    expect(FOUR.map((fact) => fact.name)).toEqual(["row_count", "total", "max", "mean"]);
    const html = card({ ...answered, facts: FOUR });
    expect(html).toContain('<span class="fact-label">Toplam</span><span class="fact-value">8.910</span>');
    expect(html).toContain(
      '<span class="fact-label">En yüksek (Siyah Çay 500 g)</span><span class="fact-value">2.480</span>',
    );
    expect(html).toContain('<span class="fact-label">Ortalama</span><span class="fact-value">1.782,00</span>');
    expect(chipRow(html).match(/<li/g)).toHaveLength(3);
    expect(chipRow(html)).not.toContain("Satır sayısı");
  });

  it("çip şeridi cevap cümlesi ile tablo arasında, kanıt panelinin dışında", () => {
    const html = card({ ...answered, facts: FOUR });
    const at = (mark) => {
      expect(html).toContain(mark);
      return html.indexOf(mark);
    };
    expect(at('id="answer-text"')).toBeLessThan(at('id="answer-facts"'));
    expect(at('id="answer-facts"')).toBeLessThan(at('id="result-table"'));
    expect(at('id="answer-facts"')).toBeLessThan(at('id="evidence-toggle"'));
  });

  it("panel kartın çip almadığı olguları listeler: çiptekiler yinelenmez", () => {
    // Updated 2026-10-26 (Eren: "otomatik olsun"): T359 moved the facts out of the evidence panel; Run 8 shows the ones the chips leave out.
    const html = card(answered);
    const body = panel(html);
    const chips = chipRow(html);
    expect(chips.match(/<li/g)).toHaveLength(3);
    // Çip şeridi üç özeti taşır; bunlar panelde tekrar okunmaz.
    for (const label of ["Toplam", "En yüksek (Siyah Çay 500 g)", "Ortalama"]) {
      expect(chips).toContain(label);
      expect(body).not.toContain(`<span class="fact-label">${label}</span>`);
    }
    // Çipe girmeyen olgular panelde kendi satırında durur.
    for (const label of ["Satır sayısı", "En düşük", "Öne çıkan", "En yüksek pay"]) {
      expect(chips).not.toContain(label);
      expect(body).toContain(`<span class="fact-label">${label}</span>`);
    }
  });

  it("tek hücrelik cevapta aynı sayı üç çipte tekrarlanmaz", () => {
    const same = { value: 191722.79, display: "191.722,79", column: "CIRO" };
    const html = card({
      ...answered,
      columns: ["CIRO"],
      rows: [[same.value]],
      row_count: 1,
      facts: [
        { name: "total", label: "Toplam", ...same },
        { name: "max", label: "En yüksek", ...same },
        { name: "mean", label: "Ortalama", ...same },
      ],
    });
    expect(chipRow(html).match(/<li/g)).toHaveLength(1);
    expect(chipRow(html)).toContain('<span class="fact-label">Toplam</span>');
  });

  it("olgusu ya da okunur okunuşu olmayan cevapta çip şeridi kurulmaz", () => {
    for (const facts of [[], null, undefined, [{ name: "total", label: "Toplam", display: "" }]]) {
      const html = card({ ...answered, facts });
      expect(html).not.toContain('id="answer-facts"');
      expect(html).not.toContain("undefined");
      expect(html).toContain('id="result-table"');
    }
  });
});
