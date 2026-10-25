import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import App, { healthDot } from "./App.jsx";

const html = renderToStaticMarkup(<App />);

describe("App kabuğu", () => {
  it("başlıkta Bilgin logosu ve iki bölüm bağlantısı var", () => {
    expect(html).toContain("<header");
    expect(html).toContain(">Bilgin</a>");
    expect(html).toContain('id="nav-ask"');
    expect(html).toContain('id="nav-rules"');
    expect(html).toContain('href="#/kurallar"');
  });

  it("sağlık noktası ilk /api/health yanıtı gelmeden önce nötr", () => {
    expect(html).toContain("dot-unknown");
    expect(html).not.toContain('class="chip"');
  });

  it("yan panel yuvası ve dar ekran düğmesi yerinde", () => {
    expect(html).toContain('id="sidebar"');
    expect(html).toContain('id="sidebar-toggle"');
    expect(html).toContain("Kayıtlılar ve geçmiş");
    expect(html).toContain('id="main"');
  });
});

describe("sağlık sözcüğü", () => {
  // Dört halin adı tek yerde: ekranla ipucu aynı sözcüğü söylemeli.
  it("her halin bir sözcüğü var", () => {
    expect(healthDot(null).label).toBe("Bilinmiyor");
    expect(healthDot({ llm: { reachable: false, reason: "timeout" } }).label).toBe("Kapalı");
    expect(healthDot({ index: { fresh: false, reason: "kural değişti" } }).label).toBe("Bayat");
    expect(healthDot({ llm: { reachable: true }, index: { fresh: true } }).label).toBe("Hazır");
  });

  it("sözcük noktanın yanında durur, nokta kendi adını taşır", () => {
    expect(html).toContain('class="health"');
    expect(html).toContain('id="health-label">Bilinmiyor</span>');
    expect(html).toContain(
      'class="dot dot-unknown" role="img" aria-label="Durum alınamadı: sunucu çalışmıyor olabilir."',
    );
  });
});
