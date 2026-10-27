// Başlangıç ekranının kartları (R7-21): kart yükünden ekrana çıkacak yazı burada kurulur, ağ
// çağrıları api.js'de kalır. Sayının okunuşu lib/format.js'nin tek kaynağından gelir. Yazılar
// R8-20'de kataloğa taşındı: her okuyan işlev `lang` alır, varsayılanı tr.
import { makeT } from "../i18n/index.js";
import { formatNumber, isNumericColumn } from "./format.js";

// config.BUSINESS_ROLES ile aynı sıra ve aynı etiketler: roller ekranlarda bu sırada listelenir.
export const BUSINESS_ROLES = [
  { role: "satis", label: "Satış" },
  { role: "satin_alma", label: "Satın alma" },
  { role: "muhasebe", label: "Muhasebe" },
  { role: "yonetim", label: "Yönetim" },
  { role: "genel", label: "Genel" },
];

// ``business_role``un iki özel değeri (R7-17): "*" her rolün kartıdır, null kişinin kendi kartıdır.
export const EVERY_ROLE = "*";
export const PERSONAL_ROLE = "";
// İki özel değerin Türkçe adı: kataloğun tr değerlerinin kendileridir (startCards.test.js
// bunları dondurur). Ekranlar adı anahtardan okur; aynı sözü iki yerde söyleyip söylemediğimizi
// StartScreen.i18n.test.jsx denetler.
export const EVERY_ROLE_LABEL = "Herkes";
export const PERSONAL_ROLE_LABEL = "Kişisel";

// Rol kodlarının katalog anahtarları: sıra BUSINESS_ROLES'de, adı t() söyler.
const ROLE_KEYS = new Map([...BUSINESS_ROLES.map((item) => [item.role, `role.${item.role}`]), [EVERY_ROLE, "start.role.every"]]);

export function roleLabel(role, lang = "tr") {
  const t = makeT(lang);
  if (role === null || role === undefined || role === "") return t("start.role.personal");
  const key = ROLE_KEYS.get(role);
  return key ? t(key) : role; // tanınmayan kod sessizce kaybolmasın, kendi adıyla görünsün
}

// Hazır soru defterinin grupları: rol sırası BUSINESS_ROLES, sonra "*", sonra kişiseller; boş
// grup yoktur, yani ekran hiç soru olmayan rol için başlık taşımaz.
export function groupByRole(rows, lang = "tr") {
  const list = Array.isArray(rows) ? rows : [];
  const order = [...BUSINESS_ROLES.map((item) => item.role), EVERY_ROLE, PERSONAL_ROLE];
  const groups = new Map();
  for (const row of list) {
    const role = row?.business_role ?? PERSONAL_ROLE;
    const key = order.includes(role) ? role : String(role);
    if (!groups.has(key)) groups.set(key, { role: key, label: roleLabel(key, lang), items: [] });
    groups.get(key).items.push(row);
  }
  // Sıra listedeki ilk karşılaşma sırası değil rol sırasıdır; tanınmayan kodlar sonda kalır.
  const known = order.filter((role) => groups.has(role));
  return [...known, ...[...groups.keys()].filter((key) => !order.includes(key))].map((key) => groups.get(key));
}

// Kartın yenilenme yazısı: "az önce" / "n dk önce" / "n sa önce". ``refreshed_at`` sözleşmede
// null olabildiği için (ve bozuk tarih için) cümle boş döner — ekran o zaman satırı hiç göstermez.
export function refreshedText(refreshedAt, now = new Date(), lang = "tr") {
  const at = Date.parse(refreshedAt ?? "");
  const base = now instanceof Date ? now.getTime() : Date.parse(now);
  if (!Number.isFinite(at) || !Number.isFinite(base)) return "";
  const t = makeT(lang);
  const minutes = Math.floor(Math.max(0, base - at) / 60000);
  if (minutes < 1) return t("time.justNow");
  if (minutes < 60) return t("time.minutes", { count: minutes });
  return t("time.hours", { count: Math.floor(minutes / 60) });
}

// Kartın büyük değeri: yalnız sayı kartının. Grafik ve tablo kartlarının yükü kendi bileşeninden
// çizilir, hata kartınınki cümlesidir — üçü de boş dize alır, ekrana "–" ya da "undefined" düşmez.
export function cardValueText(card, lang = "tr") {
  if (!card || card.error || card.display !== "number") return "";
  return formatNumber(card.value, lang);
}

// ``start/ready.suggest_display``in karşılığı: 1x1 sayı "number", grafiği olan "chart", ötekiler
// "table". Sıra da aynı — sayı hem sayıya hem grafiğe uygunsa ekran "number"ı önerir.
export function suggestDisplay({ columns, rows, chart } = {}) {
  const fields = Array.isArray(columns) ? columns : [];
  const list = Array.isArray(rows) ? rows : [];
  if (fields.length === 1 && list.length === 1 && isNumericColumn(list, 0)) return "number";
  return chart === null || chart === undefined ? "table" : "chart";
}
