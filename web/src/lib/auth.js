// Oturum kapısının kararları: kim hangi ekranı görür, girişten sonra nereye düşülür.
// Ağ işi yok: `api` içeri sokulur, böylece kararlar sahte bir kapıyla da sınanır.
import { parseRoute } from "./route.js";

export const ROLE_LABELS = { admin: "Yönetici", user: "Kullanıcı" };

export const EXPIRED_NOTE = "Oturumunuz sona erdi, lütfen yeniden giriş yapın.";

export const NOT_ALLOWED_NOTE = "Bu sayfa yalnız yöneticiye açık.";

// Harita ve kullanıcı listesi yöneticiye ait; soru ve kural ekranı her role açık
// (kural ekranı kendi içinde salt okunura döner).
const ADMIN_ONLY = new Set(["map", "users"]);

export function canSee(route, role) {
  return !ADMIN_ONLY.has(route) || role === "admin";
}

// Açılışta tek istek `me`: 401 oturum yok demektir ve giriş ekranı istenen adresi hatırlar.
// ASSUMPTION: 401 dışındaki hata (sunucuya ulaşılamıyor) kapının kararı değildir, çağırana devredilir.
export async function boot(api, hash = "#/") {
  try {
    const user = await api.me();
    // Açılış ve yenileme girişle aynı kararı verir: role açık olmayan adres, ekran hiç boyanmadan
    // soru ekranına düşer.
    const { route, note } = afterLogin(user, hash);
    return { screen: "app", user, route, requested: hash, note };
  } catch (error) {
    if (error?.status !== 401) throw error;
    return { screen: "login", user: null, requested: hash, note: null };
  }
}

// Giriş sonrası hedef: istenen ekran bu role açık değilse soru ekranına bir uyarıyla düşülür.
export function afterLogin(user, requested = "#/") {
  const route = parseRoute(requested);
  if (canSee(route, user?.role)) return { route, note: null };
  return { route: "ask", note: NOT_ALLOWED_NOTE };
}
