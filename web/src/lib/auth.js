// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// Oturum kapısının kararları: kim hangi ekranı görür, girişten sonra nereye düşülür.
// Ağ işi yok: `api` içeri sokulur, böylece kararlar sahte bir kapıyla da sınanır.
import { makeT } from "../i18n/index.js";
import { parseRoute } from "./route.js";

// Bu iki sabiti yalnız testleri donduruyor (auth.test.js, Root.test.jsx): ekranlar adı ve cümleyi
// kataloğun anahtarlarından okur, o yüzden derlenmiş arayüzde Türkçe yazı kalmaz (R8-18).
export const ROLE_LABELS = { admin: "Yönetici", user: "Kullanıcı" };

export const EXPIRED_NOTE = "Oturumunuz sona erdi, lütfen yeniden giriş yapın.";

// Harita, bağlantılar, kullanıcı listesi ve hazır soru defteri yöneticiye ait (R7-27: bir sunucunun
// kapısını yazmak, o kümenin hangi veritabanına baktığını yazmaktır); soru ve kural ekranı her role
// açık (kural ekranı kendi içinde salt okunura döner).
const ADMIN_ONLY = new Set(["map", "connections", "users", "ready"]);

export function canSee(route, role) {
  return !ADMIN_ONLY.has(route) || role === "admin";
}

// Açılışta tek istek `me`: 401 oturum yok demektir ve giriş ekranı istenen adresi hatırlar.
// ASSUMPTION: 401 dışındaki hata (sunucuya ulaşılamıyor) kapının kararı değildir, çağırana devredilir.
export async function boot(api, hash = "#/", lang = "tr") {
  try {
    const user = await api.me();
    // Açılış ve yenileme girişle aynı kararı verir: role açık olmayan adres, ekran hiç boyanmadan
    // soru ekranına düşer.
    const { route, note } = afterLogin(user, hash, lang);
    return { screen: "app", user, route, requested: hash, note };
  } catch (error) {
    if (error?.status !== 401) throw error;
    return { screen: "login", user: null, requested: hash, note: null };
  }
}

// Giriş sonrası hedef: istenen ekran bu role açık değilse soru ekranına bir uyarıyla düşülür.
// Cümlenin dili arayüz dili; `lang` verilmezse Türkçe — kapı provider'sız da kurulabiliyor.
export function afterLogin(user, requested = "#/", lang = "tr") {
  const route = parseRoute(requested);
  if (canSee(route, user?.role)) return { route, note: null };
  return { route: "ask", note: makeT(lang)("auth.notAllowed") };
}
