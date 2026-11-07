// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import Root from "./Root.jsx";
import { EXPIRED_NOTE } from "./lib/auth.js";

const NOT_ALLOWED = "Bu sayfa yalnız yöneticiye açık.";
const ADMIN = { username: "admin", role: "admin" };
const USER = { username: "analist", role: "user" };

// Cümlelerdeki kesme işareti ve tırnak SSR çıktısında düz karakter değildir; okunur metin öyle aranır.
function render(element) {
  return renderToStaticMarkup(element)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&");
}

const login = (requested = "#/", note = "") => ({ screen: "login", user: null, requested, note });
const app = (user, note = "") => ({ screen: "app", user, route: "ask", requested: "#/", note });

// Açılış adresleri: kapı hangisinde olursa olsun oturum yoksa yalnız kartı kurar.
const ENTRY_HASHES = ["", "#/", "#/kurallar", "#/harita", "#/kullanicilar", "#/bilinmeyen"];

describe("Root oturum kapısı", () => {
  it("karar verilene dek yalnız ortalanmış logo boyanır", () => {
    const html = render(<Root initial={{ screen: "checking" }} />);
    expect(html).toContain('class="gate"');
    expect(html).toContain(">Bilgin</span>");
    expect(html).not.toContain('id="login-form"');
    expect(html).not.toContain("<header");
  });

  it("oturum olmayan her açılış adresinde yalnız giriş kartı vardır", () => {
    for (const hash of ENTRY_HASHES) {
      const html = render(<Root initial={login(hash)} />);
      expect(html).toContain('id="login-form"');
      // Adı büyük harfle yazılmış da olsa tarayıcı nitelik adını küçültür: otomatik doldurma
      // `autocomplete`dur, o yüzden arama büyük/küçük harfe duyarsız.
      expect(html).toMatch(/id="login-username"[^>]*autocomplete="username"/i);
      expect(html).toMatch(/id="login-password"[^>]*autocomplete="current-password"/i);
      expect(html).toContain(">Giriş</button>");
      expect(html).not.toContain('id="nav-ask"');
      expect(html).not.toContain('id="sidebar"');
      expect(html).not.toContain("chip");
      expect(html).not.toContain('id="history-list"');
    }
  });

  it("süresi dolmuş oturumun cümlesi kartın üstünde durur", () => {
    const html = render(<Root initial={login("#/kurallar", EXPIRED_NOTE)} />);
    expect(html).toContain('id="login-note"');
    expect(html).toContain("Oturumunuz sona erdi, lütfen yeniden giriş yapın.");
    expect(render(<Root initial={login("#/")} />)).not.toContain('id="login-note"');
  });

  it("uygulama halinde başlıkta kimlik çipi ve Çıkış vardır", () => {
    const html = render(<Root initial={app(USER)} />);
    expect(html).toContain('id="user-chip"');
    expect(html).toContain("analist · Kullanıcı");
    expect(html).toContain('id="logout"');
    expect(html).toContain(">Çıkış</button>");
    expect(render(<Root initial={app(ADMIN)} />)).toContain("admin · Yönetici");
  });

  it("yetkisiz adresten düşen cümle soru ekranının üstünde durur", () => {
    const html = render(<Root initial={app(USER, NOT_ALLOWED)} />);
    expect(html).toContain('id="route-note"');
    expect(html).toContain(NOT_ALLOWED);
    expect(html).toContain('id="nav-ask"');
  });

  // Cevap kartı App'in içinde yaşar; SSR'da tutulamayacağı için ölçüt, çıkıştan sonra o ağacın
  // hiç kalmaması: kart da çip de yuvalarıyla birlikte kalkar.
  it("çıkışın render'ı cevap kartını da uygulama kabuğunu da taşımaz", () => {
    expect(render(<Root initial={app(USER)} />)).toContain('id="main"');
    const after = render(<Root initial={login("#/")} />);
    expect(after).not.toContain('id="answer-card"');
    expect(after).not.toContain('id="user-chip"');
    expect(after).not.toContain('id="logout"');
    expect(after).not.toContain('id="main"');
  });
});
