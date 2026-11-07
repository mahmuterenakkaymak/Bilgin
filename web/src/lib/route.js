// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

const ROUTES = {
  "/kurallar": "rules",
  "/harita": "map",
  "/baglantilar": "connections",
  "/kullanicilar": "users",
  "/hazir-sorular": "ready",
};

// Konuşma adresi #/c/<id>: turlar indirgeyiciden okunur, yani kimlik yolun tek sözcüğüdür (R7-15).
const CONVERSATION = /^\/c\/([^/]+)$/;

// ASSUMPTION: "#kurallar" (slash atlanırsa) da kural ekranıdır; tanınmayan her hash soru ekranına düşer.
// ASSUMPTION: "#c/<id>" de konuşmadır; kimlik küçük harfe inmiş okunur - depo uuid4().hex'in küçüğünü
// tuttuğu için indirme kaybın olmadığı tek yöndür. Boş kimlik (#/c/) ve #/c/<id>/ekstra konuşma değildir.
export function parseRoute(hash) {
  const path = String(hash ?? "")
    .trim()
    .replace(/^#/, "")
    .replace(/\/+$/, "")
    .toLowerCase();
  if (path === "" || path === "/") return "ask";
  const route = path.startsWith("/") ? path : `/${path}`;
  const conversation = CONVERSATION.exec(route);
  if (conversation) return { route: "conversation", id: conversation[1] };
  if (ROUTES[route]) return ROUTES[route];
  // ASSUMPTION: hazır soru defteri "yalnız bekleyenler" süzgecini sorgu iminde taşır
  // (#/hazir-sorular?pending=1) ki yenileme süzgeci korusun; yol hazır soru ise sorgu ekranın
  // görünüm durumudur ve rotayı değiştirmez. Öteki ekranlarda sorgu tanınmaz kalır (auth.test.js
  // "#/kurallar?x=1" → ask), o yüzden bu hoşgörü yalnız hazır soru yolunadır.
  if (route.split("?")[0] === "/hazir-sorular") return "ready";
  return "ask";
}
