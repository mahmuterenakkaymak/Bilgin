import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import App from "./App.jsx";

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
