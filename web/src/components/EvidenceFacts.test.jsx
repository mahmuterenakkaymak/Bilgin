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

// Bir etiketin kartta kaç yerde okunduğu: çip şeridi ve panel aynı `<span class="fact-label">`
// biçimini kurar, o yüzden tüm çıktıdaki sayım ikisinin toplamıdır.
function countLabel(html, label) {
  return html.split(`<span class="fact-label">${label}</span>`).length - 1;
}

describe("kanıtta çipe girmeyen olgular", () => {
  it("altı olgu: her etiket çip şeridi + panelde tam bir kez okunur", () => {
    const six = answered.facts.filter((fact) =>
      ["row_count", "total", "max", "min", "mean", "top_item"].includes(fact.name),
    );
    expect(six).toHaveLength(6);
    const html = card({ ...answered, facts: six });
    for (const fact of six) {
      expect(countLabel(html, fact.label)).toBe(1);
    }
    expect(html).toContain('id="answer-facts"');
    expect(html).toContain('id="evidence-facts"');
  });

  it("olguların hepsi çipe sığıyorsa panelde başlık da liste de kurulmaz", () => {
    const chipsOnly = answered.facts.filter((fact) => ["total", "max", "mean"].includes(fact.name));
    const html = card({ ...answered, facts: chipsOnly });
    expect(html).toContain('id="answer-facts"');
    expect(html).not.toContain('id="evidence-facts"');
    expect(html).not.toContain("Diğer olgular");
  });
});
