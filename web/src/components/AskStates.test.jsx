import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import failedIndex from "../fixtures/failed_index.json";
import failedLlm from "../fixtures/failed_llm.json";
import AskBox from "./AskBox.jsx";
import EmptyState from "./EmptyState.jsx";
import ErrorCard from "./ErrorCard.jsx";
import LoadingSteps from "./LoadingSteps.jsx";

const noop = () => {};
const EXAMPLES = [
  { question: "Eylül 2026'da satışlarımız ne kadar?", kind: "ambiguous" },
  { question: "En çok satan beş ürün hangisi?", kind: "golden" },
];

// Cümlelerdeki kesme işareti ve tırnak SSR çıktısında düz karakter değildir; okunur metin öyle aranır.
function render(node) {
  return renderToStaticMarkup(node)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&");
}

function askButton(props) {
  const html = render(<AskBox onChange={noop} onAsk={noop} {...props} />);
  return /<button[^>]*id="ask-button"[\s\S]*?<\/button>/.exec(html)?.[0] ?? "";
}

describe("AskBox", () => {
  it("soru alanı, düğme ve giriş ipucu yerinde", () => {
    const html = render(<AskBox value="" onChange={noop} onAsk={noop} />);
    expect(html).toContain('id="question"');
    expect(html).toContain('id="ask-button"');
    expect(html).toContain("Enter ile gönder, Shift+Enter alt satır.");
    expect(html).toContain(">Sor</button>");
  });

  it("boş metin ve yüklenme düğmeyi kilitler, dolu metin açar", () => {
    expect(askButton({ value: "" })).toContain("disabled");
    expect(askButton({ value: "   " })).toContain("disabled");
    expect(askButton({ value: "Kimler?", loading: true })).toContain("disabled");
    expect(askButton({ value: "Kimler?" })).not.toContain("disabled");
    expect(askButton({ value: "Kimler?", loading: true })).toContain("Cevaplanıyor…");
  });

  it("yazılan metin kutuda okunur ve örnekler çip olur", () => {
    const html = render(<AskBox value="Kaç fatura?" onChange={noop} onAsk={noop} examples={EXAMPLES} />);
    expect(html).toContain(">Kaç fatura?</textarea>");
    for (const example of EXAMPLES) {
      expect(html).toContain('class="example-chip"');
      expect(html).toContain(`>${example.question}</button>`);
    }
  });
});

describe("EmptyState", () => {
  it("iki cümle ve örnek çipler", () => {
    const html = render(<EmptyState examples={EXAMPLES} onSelect={noop} />);
    expect(html).toContain("Verinize Türkçe soru sorun");
    expect(html).toContain("Bilgin SQL'i yazar, sonucu ve nasıl hesapladığını gösterir.");
    expect(html).toContain('class="example-chip"');
    expect(html).toContain(">En çok satan beş ürün hangisi?</button>");
  });

  it("örnek yoksa yalnız iki cümle kalır", () => {
    const html = render(<EmptyState examples={[]} onSelect={noop} />);
    expect(html).toContain("Verinize Türkçe soru sorun");
    expect(html).not.toContain("example-chip");
  });

  it("örnek yoksa kart boş alanda kalmaz: cümle durumu söyler, yukarıya yönlendirir", () => {
    const html = render(<EmptyState examples={[]} onSelect={noop} />);
    expect(html).toContain('class="empty-hint"');
    expect(html).toContain("Bu veri kümesinde henüz örnek soru yok");
    expect(html).toContain("sorunu yukarıya yaz");
    expect(html).not.toContain("example-chip");
    // Yönlendirme yalnız kuralın da olmadığı durumda düşer; burada yönetici çağrısı yok.
    expect(html).not.toContain("#/kurallar");
  });

  it("örnek varken çipler durur, cümle düşmez", () => {
    const html = render(<EmptyState examples={EXAMPLES} rulesHint onSelect={noop} />);
    expect(html).toContain('class="example-chip"');
    expect(html).not.toContain("empty-hint");
    expect(html).not.toContain("#/kurallar");
  });

  it("kural da yoksa cümle İş kuralları ekranına bağlanır", () => {
    const html = render(<EmptyState examples={[]} rulesHint onSelect={noop} />);
    expect(html).toContain('href="#/kurallar"');
    expect(html).toContain(">İş kuralları</a>");
    // Cümlenin iki yarısı bitişik yazılmaz: aradaki boşluk JSX'te kendiliğinden doğmaz.
    expect(html).toContain("çevirir. Kümenin iş kuralı da yok");
  });
});

describe("LoadingSteps", () => {
  it("kart ve ilk adımın yazısı", () => {
    const html = render(<LoadingSteps />);
    expect(html).toContain('id="loading"');
    expect(html).toContain("Soru okunuyor");
    expect(html).toContain('class="loading-count"');
    expect(html).toContain('class="skeleton"');
  });
});

describe("ErrorCard", () => {
  it("model hatası: başlık, Strata ipucu ve modelin cümlesi", () => {
    const html = render(
      <ErrorCard kind={failedLlm.error.kind} message={failedLlm.error.message} onRebuild={noop} />,
    );
    expect(html).toContain('id="error-card"');
    expect(html).toContain("Model yanıt vermiyor");
    expect(html).toContain("Strata");
    expect(html).toContain("Model endpoint'ine ulaşılamadı");
    expect(html).not.toContain('id="error-rebuild"');
  });

  it("indeks hatası: başlık ve yeniden kurma düğmesi", () => {
    const html = render(
      <ErrorCard kind={failedIndex.error.kind} message={failedIndex.error.message} onRebuild={noop} />,
    );
    expect(html).toContain("İndeks eski");
    expect(html).toContain('id="error-rebuild"');
    expect(html).toContain("İndeksi yeniden kur");
    expect(html).toContain("İndeks eski: `python -m nl2sql build-index` çalıştırın.");
  });

  it("cevap üretilemedi: neden cümlesi okunur", () => {
    const html = render(
      <ErrorCard kind="no_submission" message="Model SQL göndermeden durdu." onRebuild={noop} />,
    );
    expect(html).toContain("Cevap üretilemedi");
    expect(html).toContain("Model SQL göndermeden durdu.");
  });

  it("ağ hatası: başlık bir kez yazılır", () => {
    const html = render(<ErrorCard kind="network" message="Sunucuya ulaşılamadı" onRebuild={noop} />);
    expect(html).toContain("Sunucuya ulaşılamadı");
    expect(html.match(/Sunucuya ulaşılamadı/g)).toHaveLength(1);
    expect(html).toContain("python -m nl2sql serve");
  });

  it("bilinmeyen tür genel başlığa iner", () => {
    expect(render(<ErrorCard kind="exec:sql" message="Hata." onRebuild={noop} />)).toContain("Cevap üretilemedi");
    expect(render(<ErrorCard onRebuild={noop} />)).toContain("Cevap üretilemedi");
  });
});

describe("bozuk durum örnekleri", () => {
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

  it("her durumda aynı AskPayload anahtar kümesi taşınır", () => {
    for (const fixture of [failedLlm, failedIndex]) {
      expect(Object.keys(fixture).sort()).toEqual([...PAYLOAD_KEYS].sort());
      expect(fixture.status).toBe("failed");
    }
  });
});
