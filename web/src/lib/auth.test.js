import { afterEach, describe, expect, it, vi } from "vitest";
import * as api from "./api.js";
import { EXPIRED_NOTE, ROLE_LABELS, afterLogin, boot, canSee } from "./auth.js";

const originalFetch = globalThis.fetch;

// Açılış adresleri: kök, bilinen ekran, yöneticiye ait iki yeni ekran, tanınmayan bir adres ve
// sorgu ekli bir adres.
const ENTRY_HASHES = ["", "#/", "#/kurallar", "#/harita", "#/kullanicilar", "#/bilinmeyen", "#/kurallar?x=1"];

afterEach(() => {
  globalThis.fetch = originalFetch;
});

function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => (body === undefined ? "" : JSON.stringify(body)),
  };
}

function stubFetch(result) {
  const calls = [];
  globalThis.fetch = vi.fn(async (path, init) => {
    calls.push({ path, init });
    return result;
  });
  return calls;
}

describe("boot", () => {
  it("oturum yoksa her adres yalnız /api/auth/me ile giriş ekranına düşer", async () => {
    for (const hash of ENTRY_HASHES) {
      const calls = stubFetch(jsonResponse(401, { detail: "Oturum açmanız gerekiyor." }));
      expect(await boot(api, hash)).toEqual({ screen: "login", user: null, requested: hash, note: null });
      expect(calls.map((call) => call.path)).toEqual(["/api/auth/me"]);
    }
  });

  it("oturum varsa adres ekranı belirler, yine tek istek me'dir", async () => {
    const user = { username: "admin", role: "admin" };
    const routes = {
      "": "ask",
      "#/": "ask",
      "#/kurallar": "rules",
      "#/harita": "map",
      "#/kullanicilar": "users",
      "#/bilinmeyen": "ask",
      "#/kurallar?x=1": "ask",
    };
    for (const hash of ENTRY_HASHES) {
      const calls = stubFetch(jsonResponse(200, user));
      expect(await boot(api, hash)).toEqual({
        screen: "app",
        user,
        route: routes[hash],
        requested: hash,
        note: null,
      });
      expect(calls.map((call) => call.path)).toEqual(["/api/auth/me"]);
    }
  });

  it("adres verilmezse kök istenir", async () => {
    stubFetch(jsonResponse(200, { username: "analist", role: "user" }));
    expect(await boot(api)).toEqual({
      screen: "app",
      user: { username: "analist", role: "user" },
      route: "ask",
      requested: "#/",
      note: null,
    });
  });

  it("401 dışındaki hata kapının kararı değildir, çağıranı bulur", async () => {
    stubFetch(jsonResponse(503, { detail: "Servis henüz hazır değil." }));
    await expect(boot(api, "#/kurallar")).rejects.toBeInstanceOf(api.ApiError);
  });
});

describe("canSee", () => {
  it("soru ve kural ekranı her role açık", () => {
    for (const route of ["ask", "rules"]) {
      expect(canSee(route, "admin")).toBe(true);
      expect(canSee(route, "user")).toBe(true);
    }
  });

  it("harita ve kullanıcılar yalnız yönetici", () => {
    for (const route of ["map", "users"]) {
      expect(canSee(route, "admin")).toBe(true);
      expect(canSee(route, "user")).toBe(false);
    }
  });
});

describe("afterLogin", () => {
  const ADMIN = { username: "admin", role: "admin" };
  const USER = { username: "analist", role: "user" };

  it("görülebilir adres hedefe götürür, uyarı yoktur", () => {
    const cases = [
      [ADMIN, "", "ask"],
      [ADMIN, "#/", "ask"],
      [ADMIN, "#/kurallar", "rules"],
      [ADMIN, "#/harita", "map"],
      [ADMIN, "#/kullanicilar", "users"],
      [ADMIN, "#/bilinmeyen", "ask"],
      [USER, "", "ask"],
      [USER, "#/", "ask"],
      [USER, "#/kurallar", "rules"],
      [USER, "#/bilinmeyen", "ask"],
    ];
    for (const [user, requested, route] of cases) {
      expect(afterLogin(user, requested)).toEqual({ route, note: null });
    }
  });

  it("yetkisiz adreste soru ekranına uyarıyla düşülür", () => {
    for (const requested of ["#/harita", "#/kullanicilar", "#HARITA", "#/harita/"]) {
      expect(afterLogin(USER, requested)).toEqual({ route: "ask", note: "Bu sayfa yalnız yöneticiye açık." });
    }
  });

  it("rolü okunamayan kullanıcı yönetici ekranına sokulmaz", () => {
    expect(afterLogin(null, "#/kullanicilar")).toEqual({ route: "ask", note: "Bu sayfa yalnız yöneticiye açık." });
    expect(afterLogin(null, "#/")).toEqual({ route: "ask", note: null });
  });
});

describe("etiketler ve notlar", () => {
  it("rol adları başlık çipinde görünür", () => {
    expect(ROLE_LABELS).toEqual({ admin: "Yönetici", user: "Kullanıcı" });
  });

  it("süresi dolan oturumun cümlesi sabittir", () => {
    expect(EXPIRED_NOTE).toBe("Oturumunuz sona erdi, lütfen yeniden giriş yapın.");
  });
});
