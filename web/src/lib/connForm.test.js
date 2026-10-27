// Formun sunucudaki karşılığı: cümleler engine/connections.py ve web/connections_api.py ile
// aynı yazılmak zorunda — biri değişirse öteki sessizce ayrı düşmesin diye burada tek tek
// karşılaştırılıyorlar. Kaynağı: connections.py'nin NO_* / BAD_* sabitleri ve API'nin 409'ları.
import { describe, expect, it } from "vitest";
import {
  AUTHS,
  BAD_AUTH_MESSAGE,
  BAD_PORT_MESSAGE,
  DPAPI_MESSAGE,
  EMPTY_FORM,
  ENV_SOURCE_MESSAGE,
  NO_DATABASE_MESSAGE,
  NO_PASSWORD_MESSAGE,
  NO_SERVER_MESSAGE,
  NO_USERNAME_MESSAGE,
  clientErrors,
  toForm,
  toPayload,
} from "./connForm.js";

// Sözleşme "connection (public)"ın gerçekçi bir satırı: parola ve bağlantı dizesi YOKTUR.
const ROW = {
  dataset: "wwi_real",
  server: "10.0.0.5",
  database: "WWI",
  auth: "sql",
  username: "bilgin_ro",
  options: { encrypt: true, trust_server_certificate: false, port: 1433, driver: "ODBC Driver 18 for SQL Server" },
  has_secret: true,
  last_ok_at: "2026-10-27T09:15:00+00:00",
  last_error: null,
  state: "ok",
  source: "stored",
  read_only_form: false,
};

describe("red cümleleri", () => {
  it("422'lerin altı cümlesi de deponun kendi cümleleridir", () => {
    expect(NO_SERVER_MESSAGE).toBe("Sunucu adı boş olamaz.");
    expect(NO_DATABASE_MESSAGE).toBe("Veritabanı adı boş olamaz.");
    expect(BAD_AUTH_MESSAGE).toBe("Kimlik doğrulama sql ya da windows olmalı.");
    expect(NO_USERNAME_MESSAGE).toBe("SQL kimliği için kullanıcı adı zorunlu.");
    expect(NO_PASSWORD_MESSAGE).toBe("Parola zorunlu: bu bağlantı için henüz parola saklanmadı.");
    expect(BAD_PORT_MESSAGE).toBe("Geçersiz port: 1-65535 arası bir sayı olmalı.");
  });

  it("formu okunur kılan iki 409 cümlesi de aynıdır", () => {
    expect(ENV_SOURCE_MESSAGE).toBe("Bu bağlantı ortam değişkeninden geliyor; ekrandan değiştirilemez.");
    expect(DPAPI_MESSAGE).toBe("Bu sunucuda parola saklanamaz; ortam değişkenini kullanın.");
  });

  it("kimlik doğrulamanın iki şıkkı vardır", () => {
    expect(AUTHS).toEqual(["sql", "windows"]);
  });
});

describe("toForm", () => {
  it("satırın alanlarını açar, options'ı düzleştirir", () => {
    expect(toForm(ROW)).toEqual({
      server: "10.0.0.5",
      database: "WWI",
      auth: "sql",
      username: "bilgin_ro",
      password: "",
      encrypt: true,
      trust: false,
      port: "1433",
      driver: "ODBC Driver 18 for SQL Server",
    });
  });

  it("parola hiçbir satırda yoktur: alan her zaman boş kalır", () => {
    expect(toForm({ ...ROW, password: "gizli", secret: "gizli" }).password).toBe("");
  });

  it("alanı olmayan satır varsayılan form kurar, ekran undefined görmez", () => {
    for (const row of [undefined, null, {}, { options: null }]) {
      const form = toForm(row);
      expect(form).toEqual(EMPTY_FORM);
      expect(JSON.stringify(form)).not.toMatch(/undefined|null/);
    }
    // Tanınmayan bir kimlik doğrulama select'i boş bırakmaz: ilk şıkka döner.
    expect(toForm({ auth: "oracle" }).auth).toBe("sql");
    // Port yoksa varsayılan örnek: alan boş, 0 ya da "null" değil.
    expect(toForm({ options: { port: null } }).port).toBe("");
  });
});

describe("toPayload", () => {
  it("formu API gövdesine çevirir: alanlar kırpılır, options dört anahtarla gider", () => {
    expect(toPayload({ ...EMPTY_FORM, server: " 10.0.0.5 ", database: " WWI ", username: " bilgin_ro " })).toEqual({
      server: "10.0.0.5",
      database: "WWI",
      auth: "sql",
      username: "bilgin_ro",
      password: "",
      options: { encrypt: true, trust_server_certificate: true, port: null, driver: "" },
    });
  });

  it("boş parola gönderilir: sunucu onu 'saklı olanı koru' diye okur", () => {
    expect(toPayload({ ...EMPTY_FORM, password: "" }).password).toBe("");
    expect(toPayload({ ...EMPTY_FORM, password: "yeni-parola" }).password).toBe("yeni-parola");
  });

  it("port sayıya döner; boş varsayılan örnek, bozuk değer sunucunun kendi cümlesiyle döner", () => {
    expect(toPayload({ ...EMPTY_FORM, port: " 1433 " }).options.port).toBe(1433);
    expect(toPayload({ ...EMPTY_FORM, port: "" }).options.port).toBeNull();
    expect(toPayload({ ...EMPTY_FORM, port: "abc" }).options.port).toBe("abc");
  });

  it("formda olmayan port ve sürücü korunduğu gibi gider, yoksa her kayıt varsayılana dönerdi", () => {
    const payload = toPayload(toForm(ROW));
    expect(payload.options).toEqual({
      encrypt: true,
      trust_server_certificate: false,
      port: 1433,
      driver: "ODBC Driver 18 for SQL Server",
    });
  });

  it("alanı olmayan form gövde kurar", () => {
    expect(toPayload(undefined).server).toBe("");
    expect(toPayload({}).auth).toBe("");
  });
});

describe("clientErrors", () => {
  it("boş formda sunucunun zorunlu alan cümleleri durur", () => {
    expect(clientErrors(EMPTY_FORM)).toEqual({
      server: NO_SERVER_MESSAGE,
      database: NO_DATABASE_MESSAGE,
      username: NO_USERNAME_MESSAGE,
      password: NO_PASSWORD_MESSAGE,
    });
    expect(clientErrors()).toEqual(clientErrors({}));
  });

  it("kimlik doğrulama şıkkı dışındaki bir değer kendi cümlesini alır", () => {
    // SQL dışı kimlikte kullanıcı adı ve parola sorulmaz — sunucu da önce kimliği sorar.
    expect(clientErrors({ ...EMPTY_FORM, server: "s", database: "d", auth: "oracle" })).toEqual({
      auth: BAD_AUTH_MESSAGE,
    });
  });

  it("şifreli bir satır doldurulunca hata kalmaz", () => {
    expect(clientErrors(toForm(ROW), { hasSecret: true })).toEqual({});
  });

  it("boş parola 'koru'dur: saklı sır varsa eksik sayılmaz, yoksa zorunludur", () => {
    const form = { ...EMPTY_FORM, server: "s", database: "d", username: "u", password: "" };
    expect(clientErrors(form, { hasSecret: true })).toEqual({});
    expect(clientErrors(form)).toEqual({ password: NO_PASSWORD_MESSAGE });
    expect(clientErrors(form, { hasSecret: false })).toEqual({ password: NO_PASSWORD_MESSAGE });
  });

  it("Windows kimliğinde kullanıcı adı da parola da istenmez", () => {
    expect(clientErrors({ ...EMPTY_FORM, server: "s", database: "d", auth: "windows" })).toEqual({});
  });

  it("port alanı tek başına işaretlenir: sıfır, sınır dışı ve sayı olmayan", () => {
    const base = { ...EMPTY_FORM, server: "s", database: "d", username: "u", password: "p" };
    for (const port of ["0", "65536", "abc", "1433.5"]) {
      expect(clientErrors({ ...base, port })).toEqual({ port: BAD_PORT_MESSAGE });
    }
    expect(clientErrors({ ...base, port: "1433" })).toEqual({});
    expect(clientErrors({ ...base, port: "" })).toEqual({});
  });

  it("her eksik alan kendi anahtarıyla işaretlenir", () => {
    const errors = clientErrors({ ...EMPTY_FORM, server: "", database: "d" });
    expect(Object.keys(errors).sort()).toEqual(["password", "server", "username"]);
  });
});
