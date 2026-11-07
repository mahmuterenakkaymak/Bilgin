// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// Başlığın veritabanı çipi ve düşmüş veritabanının bandı SSR ile kuruluyor: noktanın tonu,
// ipucunun kime ne söylediği ve bandın hangi halde açıldığı boya çıkmadan da okunur. Yoklamanın
// kendisi sunucuda (tests/test_web_db_status.py), burada yalnız /api/health'ın `db` bloğunun
// ekranda ne yazdığı var.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { DbBanner, DbDot, dbStatus } from "./DbStatus.jsx";

const render = (element) => renderToStaticMarkup(element);
const title = (html) => /title="([^"]*)"/.exec(html)?.[1] ?? "";

const CHECKED = "2026-10-27T09:15:00+00:00";
const DOWN = "Veritabanına bağlanılamıyor, yöneticinize haber verin.";
const DRIVER = "TCP Provider: No connection could be made.";

// Sözleşme "health db": durum, yoklamanın saati ve iki cümle — yönetici cümlesi kullanıcının
// cevabında hiç yoktur.
const db = (state, extra = {}) => ({
  state,
  checked_at: CHECKED,
  message: state === "down" ? DOWN : null,
  message_admin: state === "down" ? DRIVER : null,
  ...extra,
});

describe("veritabanı noktası", () => {
  it("her halin bir adı ve tonu var", () => {
    for (const state of ["ok", "down", "none", "unknown"]) {
      const html = render(<DbDot db={db(state)} />);
      expect(html).toContain('id="db-dot"');
      expect(html).toContain(`class="db-dot db-dot-${state}"`);
      expect(html).toContain(">Veritabanı</span>");
    }
  });

  it("yoklama olmayan ya da tanınmayan cevap nötr tonu okur", () => {
    expect(dbStatus(undefined).tone).toBe("unknown");
    expect(dbStatus({ state: "yeni-duyum" }).tone).toBe("unknown");
    expect(render(<DbDot db={undefined} />)).toContain('class="db-dot db-dot-unknown"');
  });

  it("kullanıcı genel cümleyi ve saati okur, sürücü cümlesini okumaz", () => {
    const html = render(<DbDot db={db("down")} />);
    const tip = title(html);
    expect(tip).toContain(DOWN);
    expect(tip).toContain("Son kontrol:");
    expect(tip).not.toContain(DRIVER);
    expect(html).not.toContain('href="#/baglantilar"');
  });

  it("yönetici sürücü cümlesini ve bağlantı ekranının adresini görür", () => {
    const html = render(<DbDot db={db("down")} isAdmin />);
    const tip = title(html);
    expect(tip).toContain(DOWN);
    expect(tip).toContain(DRIVER);
    expect(html).toContain('href="#/baglantilar"');
  });

  it("saati olmayan hal saatsiz okunur", () => {
    const tip = title(render(<DbDot db={db("unknown", { checked_at: null })} />));
    expect(tip).toBe("Veritabanı durumu henüz ölçülmedi.");
  });
});

describe("veritabanı bandı", () => {
  it("bant yalnız düşmüş veritabanında açılır", () => {
    for (const state of ["ok", "none", "unknown"]) {
      expect(render(<DbBanner db={db(state)} isAdmin />)).toBe("");
    }
    expect(render(<DbBanner db={db("down")} />)).toContain('id="db-banner"');
  });

  it("bant cümleyi söyler; sürücü satırı ve adresi yöneticiye aittir", () => {
    const user = render(<DbBanner db={db("down")} />);
    expect(user).toContain(DOWN);
    expect(user).not.toContain(DRIVER);
    expect(user).not.toContain('href="#/baglantilar"');

    const admin = render(<DbBanner db={db("down")} isAdmin />);
    expect(admin).toContain(DRIVER);
    expect(admin).toContain('href="#/baglantilar"');
  });
});
