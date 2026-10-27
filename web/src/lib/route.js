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
  return ROUTES[route] ?? "ask";
}
