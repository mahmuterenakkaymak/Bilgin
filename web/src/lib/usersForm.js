// Kullanıcı formunun sunucudaki karşılığı: red cümleleri auth/store.py ve auth/passwords.py
// ile aynı yazılır ki kullanıcı eksik formu göndermek için bir gidiş-gerişi beklemesin (R6-19).
// Sunucu adı küçük harfe çevirip öyle denetliyor; burada da sıralama aynı, yoksa "Analit2"
// burada reddolunup orada kabul edilirdi.

const NAME_PATTERN = /^[a-z0-9_.-]{3,32}$/;

// nl2sql/config.PASSWORD_MIN_LEN: arayüz Python'u okuyamadığı için değeri burada da duruyor.
export const PASSWORD_MIN_LEN = 10;

export const ROLES = ["admin", "user"];

export const NAME_MESSAGE =
  "Kullanıcı adı 3-32 karakter olmalı ve yalnız küçük harf, rakam, . _ - içerebilir.";
export const PASSWORD_MESSAGE = `Parola en az ${PASSWORD_MIN_LEN} karakter olmalı.`;
export const MATCH_MESSAGE = "Parolalar eşleşmiyor.";
export const ROLE_MESSAGE = "Rol admin ya da user olmalı.";

// API'nin gövdesi: parolanın tekrarı yalnız denetim içindir, sunucuya gitmez.
export function toPayload(form) {
  const item = form ?? {};
  return {
    username: text(item.username).trim().toLowerCase(),
    password: text(item.password),
    role: text(item.role).trim(),
  };
}

export function clientErrors(form) {
  const item = form ?? {};
  const payload = toPayload(form);
  const errors = {};
  if (!NAME_PATTERN.test(payload.username)) errors.username = NAME_MESSAGE;
  if (payload.password.length < PASSWORD_MIN_LEN) errors.password = PASSWORD_MESSAGE;
  if (text(item.password2) !== payload.password) errors.password2 = MATCH_MESSAGE;
  if (!ROLES.includes(payload.role)) errors.role = ROLE_MESSAGE;
  return errors;
}

function text(value) {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}
