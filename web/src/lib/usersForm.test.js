// Cümleler sunucunun sözüdür (auth/store.py, auth/passwords.py): burada sabitlenmeleri, biri
// arayüzde yeniden yazıldığında sunucuya da bakılmasını zorunlu kılsın.
import { describe, expect, it } from "vitest";
import {
  MATCH_MESSAGE,
  NAME_MESSAGE,
  PASSWORD_MESSAGE,
  PASSWORD_MIN_LEN,
  ROLE_MESSAGE,
  clientErrors,
  toPayload,
} from "./usersForm.js";

const VALID = { username: "analist2", password: "Uzun-Parola-10", password2: "Uzun-Parola-10", role: "user" };

describe("toPayload", () => {
  it("parolanın tekrarını gövdeye almaz; adı kırpıp küçük harfe çevirir", () => {
    expect(toPayload({ username: "  Analist2  ", password: "a-parola", password2: "a-parola", role: "admin" })).toEqual({
      username: "analist2",
      password: "a-parola",
      role: "admin",
    });
  });

  it("eksik alan boş dizedir; gövde undefined ya da null taşımaz", () => {
    for (const form of [undefined, null, {}, { username: null, role: null }]) {
      const payload = toPayload(form);
      expect(payload).toEqual({ username: "", password: "", role: "" });
      expect(JSON.stringify(payload)).not.toMatch(/undefined|null/);
    }
  });

  it("paroladaki boşluklar korunur — sunucu da kırpıyor", () => {
    expect(toPayload({ ...VALID, password: " 1234567890 " }).password).toBe(" 1234567890 ");
  });
});

describe("clientErrors", () => {
  it("boş formda zorunlu üç alanın sunucu cümlesi alt alta yazılır", () => {
    expect(clientErrors({})).toEqual({ username: NAME_MESSAGE, password: PASSWORD_MESSAGE, role: ROLE_MESSAGE });
    expect(clientErrors()).toEqual(clientErrors({}));
  });

  it("temiz formda hata yoktur; yönetici de temizdir", () => {
    expect(clientErrors(VALID)).toEqual({});
    expect(clientErrors({ ...VALID, role: "admin" })).toEqual({});
  });

  it("adın kalıbı: kısa, uzun, boşluklu ve Türkçe harfli reddolunur; büyük harf sunucu gibi geçer", () => {
    for (const username of ["ab", "a".repeat(33), "ana list", "analıst", "analist2!"]) {
      expect(clientErrors({ ...VALID, username })).toEqual({ username: NAME_MESSAGE });
    }
    expect(clientErrors({ ...VALID, username: "a.b-c_1" })).toEqual({});
    expect(clientErrors({ ...VALID, username: "Analist2" })).toEqual({});
  });

  it("parola uzunluğu: dokuz red, on kabul", () => {
    expect(clientErrors({ ...VALID, password: "123456789", password2: "123456789" })).toEqual({
      password: PASSWORD_MESSAGE,
    });
    expect(clientErrors({ ...VALID, password: "1234567890", password2: "1234567890" })).toEqual({});
  });

  it("eşleşmeyen parola tekrar alanının altına yazılır, ilki temiz kalır", () => {
    expect(clientErrors({ ...VALID, password2: "Başka-Parola-1" })).toEqual({ password2: MATCH_MESSAGE });
  });

  it("rol yalnız admin ya da user olabilir", () => {
    expect(clientErrors({ ...VALID, role: "yönetici" })).toEqual({ role: ROLE_MESSAGE });
    expect(clientErrors({ ...VALID, role: " " })).toEqual({ role: ROLE_MESSAGE });
  });

  it("cümleler sunucudakiyle harfi harfine aynıdır", () => {
    expect(PASSWORD_MIN_LEN).toBe(10);
    expect(NAME_MESSAGE).toBe(
      "Kullanıcı adı 3-32 karakter olmalı ve yalnız küçük harf, rakam, . _ - içerebilir.",
    );
    expect(PASSWORD_MESSAGE).toBe("Parola en az 10 karakter olmalı.");
    expect(MATCH_MESSAGE).toBe("Parolalar eşleşmiyor.");
    expect(ROLE_MESSAGE).toBe("Rol admin ya da user olmalı.");
  });
});
