// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// Kullanıcı formunun sunucudaki karşılığı: red cümleleri auth/store.py ve auth/passwords.py
// ile aynı yazılır ki kullanıcı eksik formu göndermek için bir gidiş-gerişi beklemesin (R6-19).
// Sunucu adı küçük harfe çevirip öyle denetliyor; burada da sıralama aynı, yoksa "Analit2"
// burada reddolunup orada kabul edilirdi. Cümleler R8-20'de kataloğa taşındı; aşağıdaki dört
// sabit Türkçe katalog değerlerinin kendisidir — sunucunun tr cümleleriyle de aynı olduğu için
// testler bu sabitleri beklemeye devam ediyor.
import { makeT } from "../i18n/index.js";

const NAME_PATTERN = /^[a-z0-9_.-]{3,32}$/;

// nl2sql/config.PASSWORD_MIN_LEN: arayüz Python'u okuyamadığı için değeri burada da duruyor.
export const PASSWORD_MIN_LEN = 10;

export const ROLES = ["admin", "user"];

export const NAME_MESSAGE =
  "Kullanıcı adı 3-32 karakter olmalı ve yalnız küçük harf, rakam, . _ - içerebilir.";
export const PASSWORD_MESSAGE = `Parola en az ${PASSWORD_MIN_LEN} karakter olmalı.`;
export const MATCH_MESSAGE = "Parolalar eşleşmiyor.";
export const ROLE_MESSAGE = "Rol admin ya da user olmalı.";

// Reddin cümlesi kataloğun anahtarı; `min` parolanın asgari uzunluğu — ikisi tek yerde dursun.
export const MESSAGE_KEYS = {
  username: "users.form.username",
  password: "users.form.password",
  password2: "users.form.password2",
  role: "users.form.role",
};

// API'nin gövdesi: parolanın tekrarı yalnız denetim içindir, sunucuya gitmez.
export function toPayload(form) {
  const item = form ?? {};
  return {
    username: text(item.username).trim().toLowerCase(),
    password: text(item.password),
    role: text(item.role).trim(),
  };
}

// `lang` arayüzün dili: boş formun reddi sunucuya varmadan kullanıcının dilinde okunur.
export function clientErrors(form, lang = "tr") {
  const t = makeT(lang);
  const item = form ?? {};
  const payload = toPayload(form);
  const errors = {};
  if (!NAME_PATTERN.test(payload.username)) errors.username = t(MESSAGE_KEYS.username);
  if (payload.password.length < PASSWORD_MIN_LEN) {
    errors.password = t(MESSAGE_KEYS.password, { min: PASSWORD_MIN_LEN });
  }
  if (text(item.password2) !== payload.password) errors.password2 = t(MESSAGE_KEYS.password2);
  if (!ROLES.includes(payload.role)) errors.role = t(MESSAGE_KEYS.role);
  return errors;
}

function text(value) {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}
