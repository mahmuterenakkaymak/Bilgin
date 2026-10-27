// Kenar çubuklarının kısa zamanı (R8-19): "4 dk önce" / "4 min ago". Cümleler kataloğunda durduğu
// için çeviriyi çağırandan alır — KAYITLILAR ve GEÇMİŞ aynı zamanı aynı cümleyle yazar.
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

function startOfDay(ms) {
  const day = new Date(ms);
  day.setHours(0, 0, 0, 0);
  return day.getTime();
}

// "Dün" takvimsel bir fark, o yüzden gün sayısına yerel gecenin başından iniliyor.
// ASSUMPTION: ts boş ya da okunamazsa boş dize - satır zamansız kalır.
export function relativeTime(value, now, t) {
  if (typeof value !== "string" || !value) return "";
  const then = Date.parse(value);
  if (!Number.isFinite(then)) return "";
  const diff = now - then;
  if (diff < MINUTE) return t("time.now");
  if (diff < HOUR) return t("time.minutes", { count: Math.floor(diff / MINUTE) });
  if (diff < DAY) return t("time.hours", { count: Math.floor(diff / HOUR) });
  const days = Math.round((startOfDay(now) - startOfDay(then)) / DAY);
  if (days <= 1) return t("time.yesterday");
  if (days < 7) return t("time.days", { count: days });
  if (days < 30) {
    const weeks = Math.floor(days / 7);
    return t(weeks === 1 ? "time.weeks.one" : "time.weeks", { count: weeks });
  }
  if (days < 365) {
    const months = Math.floor(days / 30);
    return t(months === 1 ? "time.months.one" : "time.months", { count: months });
  }
  const years = Math.floor(days / 365);
  return t(years === 1 ? "time.years.one" : "time.years", { count: years });
}
