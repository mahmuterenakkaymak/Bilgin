import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import answered from "../fixtures/answered.json";
import empty from "../fixtures/empty.json";
import masked from "../fixtures/masked.json";
import truncated from "../fixtures/truncated.json";
import AnswerCard from "./AnswerCard.jsx";
import Evidence from "./Evidence.jsx";
import ResultTable from "./ResultTable.jsx";
import Warnings from "./Warnings.jsx";

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

const PAYLOAD_KEYS = [
  "status",
  "question",
  "choice",
  "answer_text",
  "narration_source",
  "chart",
  "facts",
  "columns",
  "rows",
  "row_count",
  "truncated",
  "sql",
  "tables_used",
  "rules_used",
  "masked_columns",
  "warnings",
  "notes",
  "mode",
  "dataset",
  "model",
  "timings",
  "audit_id",
  "clarification",
  "error",
  "steps",
];

// report/chart.chart_spec'in çıktısı: işlevi olmayan düz ECharts JSON'u + `bilgin` ipucu (R5-6).
const CHART = {
  type: "bar",
  option: {
    tooltip: { trigger: "axis" },
    grid: { left: 40 },
    xAxis: { type: "category", data: ["Siyah Çay 500 g", "Filtre Kahve 100 g"] },
    yAxis: { type: "value" },
    series: [{ type: "bar", name: "SATIS_MIKTARI", data: [2480, 1930] }],
    bilgin: { value_format: "number", value_column: "SATIS_MIKTARI", label_column: "URUN_ADI" },
  },
};

describe("AnswerCard", () => {
  it("durum satırı, cevap cümlesi ve kartın bütün kimlikleri", () => {
    const html = card(answered);
    expect(html).toContain('id="answer-card"');
    expect(html).toContain('id="answer-text"');
    expect(html).toContain('id="result-table"');
    expect(html).toContain('id="export-csv"');
    expect(html).toContain('id="export-xlsx"');
    expect(html).toContain('id="save-question"');
    expect(html).toContain('id="evidence-toggle"');
    expect(html).toContain('id="evidence"');
    expect(html).toContain("✓ Cevaplandı · full_rules · 8,3 sn");
    expect(html).toContain("Eylül 2026'da en çok satan ürün 2.480 adetle Siyah Çay 500 g oldu");
  });

  it("ölçülür süre yoksa durum satırı süreyi yazmaz", () => {
    for (const total of [0, 0.04, null]) {
      const html = card({ ...answered, timings: { ...answered.timings, total_s: total } });
      expect(html).toContain("✓ Cevaplandı · full_rules");
      expect(html).not.toContain("0,0 sn");
    }
  });

  it("uyarısız cevapta uyarı bandı kurulmaz, kesik olmayan sonuçta alt yazı yoktur", () => {
    const html = card(answered);
    expect(html).not.toContain('id="warnings"');
    expect(html).not.toContain("satır gösteriliyor");
  });

  it("indirme bağlantıları denetim kaydının adresini taşır", () => {
    const html = card(answered);
    expect(html).toContain('href="/api/export/4c1d9e07a5b2.csv"');
    expect(html).toContain('href="/api/export/4c1d9e07a5b2.xlsx"');
    expect(html).toContain("Tamamını indir:");
    expect(html).toContain(">Soruyu kaydet</button>");
  });

  it("denetim kaydı yoksa indirme bağlantısı kurulmaz", () => {
    const html = card({ ...answered, audit_id: "" });
    expect(html).not.toContain('id="export-csv"');
    expect(html).not.toContain('id="export-xlsx"');
    expect(html).toContain('id="save-question"');
  });

  it("grafik kartın içindedir: tablonun altında, düğmelerin ve kanıtın üstünde", () => {
    const html = card({ ...answered, chart: CHART });
    const at = (mark) => {
      expect(html).toContain(mark);
      return html.indexOf(mark);
    };
    const cardStart = at('id="answer-card"');
    const table = at('id="result-table"');
    const chart = at('id="chart"');
    const actions = at('id="save-question"');
    const evidence = at('id="evidence-toggle"');
    expect(chart).toBeGreaterThan(cardStart);
    expect(chart).toBeGreaterThan(table);
    expect(chart).toBeLessThan(actions);
    expect(chart).toBeLessThan(evidence);
  });

  it("grafsiz cevapta #chart hiç kurulmaz, boş kutu kalmaz", () => {
    const html = card(answered);
    expect(html).toContain('id="answer-card"');
    expect(html).not.toContain('id="chart"');
    expect(html).not.toContain('class="chart"');
  });
});

describe("ResultTable", () => {
  it("sayılar Türkçe ve sağ yaslı, metin sütun yaslanmaz", () => {
    const html = card(answered);
    expect(html).toContain('<th scope="col" class="num">SATIS_MIKTARI</th>');
    expect(html).toContain('<td class="num">2.480</td>');
    expect(html).toContain("<td>STK0012</td>");
    expect(html).toContain("<td>Siyah Çay 500 g</td>");
    expect(html).not.toContain("2480");
  });

  it("boş hücre \"–\" olarak okunur", () => {
    const html = card(truncated);
    expect(html).toContain("<td>–</td>");
    expect(html).toContain('<td class="num">315,75</td>');
  });

  it("kesik sonuçta alt yazı gösterileni ve toplamı söyler", () => {
    expect(card(truncated)).toContain("İlk 8 satır gösteriliyor (toplam 1.234).");
  });

  it("iki yüz satırdan fazlası ekrana çıkmaz, alt yazı sınırı yazar", () => {
    const rows = Array.from({ length: 240 }, (_, index) => [`FTH${index}`, index + 1]);
    const html = render(
      <ResultTable columns={["FISNO", "ADET"]} rows={rows} rowCount={1234} truncated />,
    );
    expect(html).toContain("İlk 200 satır gösteriliyor (toplam 1.234).");
    expect(html).toContain("<td>FTH199</td>");
    expect(html).not.toContain("<td>FTH239</td>");
  });

  it("boş sonuç tablonun yerini alan cümleyi gösterir", () => {
    const html = card(empty);
    expect(html).toContain("Bu soruya uyan kayıt yok.");
    expect(html).not.toContain('id="result-table"');
  });

  it("satır yoksa toplamı uydurmaz", () => {
    const html = render(<ResultTable columns={["A"]} rows={[]} rowCount={0} truncated={false} />);
    expect(html).toContain("Bu soruya uyan kayıt yok.");
  });
});

describe("Warnings", () => {
  it("her uyarı kendi satırıdır", () => {
    const html = render(
      <Warnings
        warnings={[
          { code: "empty", message: "Sonuç boş: bu koşullara uyan kayıt yok.", column: null },
          { code: "masked", message: "Maskelendi: IBAN — kişisel veri gösterilmez.", column: null },
        ]}
      />,
    );
    expect(html).toContain('id="warnings"');
    expect(html.match(/⚠/g)).toHaveLength(2);
  });

  it("uyarı yoksa bant hiç kurulmaz", () => {
    expect(render(<Warnings warnings={[]} />)).toBe("");
    expect(render(<Warnings />)).toBe("");
  });
});

describe("boş ve maskeli cevaplar", () => {
  it("boş sonuç: boş uyarısı tek başına bantta okunur", () => {
    const html = card(empty);
    expect(html).toContain('id="warnings"');
    expect(html).toContain("Sonuç boş: bu koşullara uyan kayıt yok.");
    expect(html.match(/⚠/g)).toHaveLength(1);
  });

  it("maskeli kolonlar uyarıda ve tablada maskeli hücresiyle okunur", () => {
    const html = card(masked);
    expect(html).toContain("Maskelendi: AD_SOYAD, TELEFON, IBAN — kişisel veri gösterilmez.");
    expect(html).toContain("<td>A.Y.</td>");
    expect(html).toContain("<td>*** ** 456</td>");
    expect(html).toContain("<td>TR** **** **** **** 9876</td>");
    // Maskeli hücreler metindir: sayı gibi sağ yaslama almaz.
    expect(html).not.toContain('<td class="num">*** ** 456</td>');
  });

  it("katlanan join uyarısı kesik sonuçla birlikte okunur", () => {
    const html = card(truncated);
    expect(html).toContain("Join sonrası 1234 satır, sürücü tablo TBLSTHAR 412 satır (3,0x)");
  });
});

describe("Evidence", () => {
  it("SQL, kopyalama düğmesi, tablolar, kurallar, mod ve denetim kaydı", () => {
    const html = render(<Evidence payload={answered} />);
    expect(html).toContain('id="evidence-toggle"');
    expect(html).toContain("Nasıl hesapladım");
    expect(html).toContain('id="evidence"');
    expect(html).toContain("SUM(s.STHAR_GCMIK)");
    expect(html).toContain('id="copy-sql"');
    expect(html).toContain(">Kopyala</button>");
    expect(html).toContain("<dt>Mod</dt><dd>full_rules</dd>");
    expect(html).toContain("<dt>Tablolar</dt><dd>TBLSTHAR, TBLSTSABIT</dd>");
    expect(html).toContain("<dt>Kurallar</dt><dd>–</dd>");
    expect(html).toContain("<dt>Maskeli kolonlar</dt><dd>–</dd>");
    expect(html).toContain('<dt>Denetim kaydı</dt><dd class="audit-id">4c1d9e07a5b2</dd>');
  });

  it("olgular Türkçe okunuşlarıyla, süreler ve notlar kanıtta durur", () => {
    const html = render(<Evidence payload={answered} />);
    expect(html).toContain('<span class="fact-label">Toplam</span><span class="fact-value">8.910</span>');
    expect(html).toContain('<span class="fact-label">En yüksek pay</span><span class="fact-value">%27,8</span>');
    expect(html).toContain("ajan 6,4 sn · sorgu 12,5 ms · anlatı 1,9 sn · toplam 8,3 sn");
    expect(html).toContain("Satır sayısı");

    const maskedHtml = render(<Evidence payload={masked} />);
    expect(maskedHtml).toContain("<dt>Maskeli kolonlar</dt><dd>AD_SOYAD, TELEFON, IBAN</dd>");
    expect(maskedHtml).toContain("İndeks yok/eski; full modda çalışılıyor.");
  });

  it("adımlar ✓ ve ✗ ile okunur", () => {
    const html = render(<Evidence payload={masked} />);
    expect(html).toContain('class="step"');
    expect(html).toContain('class="step step-failed"');
    expect(html).toContain(">✓</span>");
    expect(html).toContain(">✗</span>");
    expect(html).toContain('class="step-tool">run_sql</span>');
    expect(html).toContain("Invalid column name");
  });

  it("alanı eksik payload çökmez, boşluğu – ile gösterir", () => {
    const html = render(<Evidence payload={{}} />);
    expect(html).toContain("<dt>Mod</dt><dd>–</dd>");
    expect(html).toContain('<dt>Denetim kaydı</dt><dd class="audit-id">–</dd>');
    expect(html).not.toContain("undefined");
    expect(html).not.toContain("NaN");
  });
});

describe("durum örnekleri", () => {
  it("her örnekte aynı AskPayload anahtar kümesi taşınır", () => {
    for (const fixture of [answered, truncated, empty, masked]) {
      expect(Object.keys(fixture).sort()).toEqual([...PAYLOAD_KEYS].sort());
      expect(fixture.status).toBe("answered");
    }
  });
});
