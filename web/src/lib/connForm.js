// Bağlantı formunun sunucudaki karşılığı: red cümleleri engine/connections.py ve
// web/connections_api.py ile birebir aynı yazılır ki yönetici eksik formu göndermek için bir
// gidiş-gerişi beklemesin. Denetleme sırası da oradakiyle aynı: sunucu adı, veritabanı, kimlik
// doğrulama, kullanıcı adı, parola, port.
//
// Boş parola "koru"dur: depo yeni sır blobunu NULL bırakıp saklı olanı taşıyor (COALESCE), o
// yüzden alan boşsa parola yalnız hiç saklanmamışsa zorunludur — sunucunun bildiği bu tek gerçeği
// form `has_secret` alanından okur.

export const AUTHS = ["sql", "windows"];

export const AUTH_LABELS = { sql: "SQL kimliği (kullanıcı adı ve parola)", windows: "Windows kimliği (sunucunun kendi hesabı)" };

export const NO_SERVER_MESSAGE = "Sunucu adı boş olamaz.";
export const NO_DATABASE_MESSAGE = "Veritabanı adı boş olamaz.";
export const BAD_AUTH_MESSAGE = "Kimlik doğrulama sql ya da windows olmalı.";
export const NO_USERNAME_MESSAGE = "SQL kimliği için kullanıcı adı zorunlu.";
export const NO_PASSWORD_MESSAGE = "Parola zorunlu: bu bağlantı için henüz parola saklanmadı.";
export const BAD_PORT_MESSAGE = "Geçersiz port: 1-65535 arası bir sayı olmalı.";

// 409'un iki cümlesi (connections_api): formu okunur kılanlar. Ortam değişkeni sunucudan okunur,
// parolanın saklanamadığı ise ilk kayıt denemesinde anlaşılır — ekran cümleyi tanır.
export const ENV_SOURCE_MESSAGE = "Bu bağlantı ortam değişkeninden geliyor; ekrandan değiştirilemez.";
export const DPAPI_MESSAGE = "Bu sunucuda parola saklanamaz; ortam değişkenini kullanın.";

// Sözleşme "connection (public)"ın alanları + parola. Port ve sürücü formda değildir (R7-27'in
// formu onları istemiyor) ama formla birlikte dolaşır, yoksa her kayıt varsayılanlarına dönerdi.
export const EMPTY_FORM = {
  server: "",
  database: "",
  auth: "sql",
  username: "",
  password: "",
  encrypt: true,
  trust: true,
  port: "",
  driver: "",
};

// Satır → form: parola hiçbir yerde okunmadığı için boş kalır, options'ın dört alanı açılır.
// Alan yoksa varsayılanlar okunur ki ekran `undefined` görmesin.
export function toForm(row) {
  const item = row ?? {};
  const options = item.options ?? {};
  return {
    server: text(item.server),
    database: text(item.database),
    auth: AUTHS.includes(item.auth) ? item.auth : "sql",
    username: text(item.username),
    password: "",
    encrypt: options.encrypt !== false,
    trust: options.trust_server_certificate !== false,
    port: options.port === null || options.port === undefined ? "" : String(options.port),
    driver: text(options.driver),
  };
}

// Form → API gövdesi: boş `password` anahtarı gider, sunucu onu "koru" diye okur.
export function toPayload(form) {
  const item = form ?? {};
  return {
    server: text(item.server).trim(),
    database: text(item.database).trim(),
    auth: text(item.auth).trim().toLowerCase(),
    username: text(item.username).trim(),
    password: text(item.password),
    options: {
      encrypt: item.encrypt !== false,
      trust_server_certificate: item.trust !== false,
      port: portValue(item.port),
      driver: text(item.driver).trim(),
    },
  };
}

// `hasSecret` açılan satırın `has_secret`ı: saklı sır varsa boş parola bir eksik değildir.
export function clientErrors(form, { hasSecret = false } = {}) {
  const payload = toPayload(form);
  const sql = payload.auth === "sql";
  const errors = {};
  if (!payload.server) errors.server = NO_SERVER_MESSAGE;
  if (!payload.database) errors.database = NO_DATABASE_MESSAGE;
  if (!AUTHS.includes(payload.auth)) errors.auth = BAD_AUTH_MESSAGE;
  if (sql && !payload.username) errors.username = NO_USERNAME_MESSAGE;
  if (sql && !payload.password && !hasSecret) errors.password = NO_PASSWORD_MESSAGE;
  if (badPort(payload.options.port)) errors.port = BAD_PORT_MESSAGE;
  return errors;
}

// Boş port varsayılan örnek demektir; sayıya dönmeyen değer sunucuya olduğu gibi gider, oradan
// kendi cümlesiyle döner.
function portValue(value) {
  const raw = text(value).trim();
  if (!raw) return null;
  return /^\d+$/.test(raw) ? Number(raw) : raw;
}

function badPort(value) {
  return value !== null && (!Number.isInteger(value) || value < 1 || value > 65535);
}

function text(value) {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}
