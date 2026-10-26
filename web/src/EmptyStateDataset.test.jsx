import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import EmptyState from "./components/EmptyState.jsx";

const noop = () => {};
const EXAMPLES = [{ question: "En çok satan beş ürün hangisi?", kind: "golden" }];

// Kesme işareti ve tırnak SSR çıktısında düz karakter değildir; okunur metin öyle aranır.
function render(node) {
  return renderToStaticMarkup(node)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&");
}

describe("boş ekran hangi dünyada sorulduğunu söyler", () => {
  it("ad gelince lead onu taşır", () => {
    const html = render(<EmptyState examples={EXAMPLES} datasetName="Sentetik ERP" onSelect={noop} />);
    expect(html).toContain("Sentetik ERP");
    expect(html).toContain("«Sentetik ERP» üzerinde soruyorsun; örnekler onun tablolarından.");
  });

  it("ad gelmeyince cümle bugünkü, değişmeden", () => {
    const html = render(<EmptyState examples={EXAMPLES} onSelect={noop} />);
    expect(html).toContain("Bilgin SQL'i yazar, sonucu ve nasıl hesapladığını gösterir.");
    expect(html).not.toContain("üzerinde soruyorsun");
  });

  it("yerleşim aynı: iki cümle ve çipler", () => {
    const html = render(<EmptyState examples={EXAMPLES} datasetName="WWI" onSelect={noop} />);
    expect(html).toContain('class="screen-title"');
    expect(html).toContain('class="screen-lead"');
    expect(html).toContain('class="example-chip"');
  });
});
