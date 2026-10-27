// Ekrana çıkan her sayının tek kaynağı: Python tarafındaki report/fmt.py ile aynı okunuş.
// Binlik ayıracı nokta, ondalık virgül, yüzde işareti sayının önünde; boş hücre "0" değil "–".
// Aynı sayı dil anahtarıyla da yazılır (R8-16): İngilizcede binlik virgül, ondalık nokta, yüzde
// sonda ve ölçek K/M/B'dir. Türkçe okunuş eskisiyle bayt bayt aynıdır; yokluk iki dilde de "–".
const NULL_TEXT = "–";
const COMPACT_MIN = 10_000;
const LOCALES = { tr: "tr-TR", en: "en-US" };
const SCALES = {
  tr: [[1_000_000_000, "milyar"], [1_000_000, "milyon"], [1_000, "bin"]],
  en: [[1_000_000_000, "B"], [1_000_000, "M"], [1_000, "K"]],
};

// ASSUMPTION: tanınmayan dil Türkçe okur — provider'sız ilk boyama ve dili olmayan payload tr'dir.
export function normalizeLang(lang) {
  return lang === "en" ? "en" : "tr";
}

const NUMBERS = new Map();
const DATES = new Map();

// Hücre başına yeni Intl kurulmaz: dil ve basamak sayısı başına bir tane tutulur.
function numberFormat(code, min, max) {
  const id = `${code}:${min ?? "-"}:${max ?? "-"}`;
  let formatter = NUMBERS.get(id);
  if (!formatter) {
    const options = {};
    if (min !== null) options.minimumFractionDigits = min;
    if (max !== null) options.maximumFractionDigits = max;
    formatter = new Intl.NumberFormat(code, options);
    NUMBERS.set(id, formatter);
  }
  return formatter;
}

// `decimals` verilmezse kesirli sayı en çok iki basamakla yazılır; verilirse tam olarak o kadar
// yazılır — olgunun sunucudaki okunuşu basamağını bu yolla taşır.
export function formatNumber(value, lang = "tr", decimals = null) {
  if (typeof value !== "number" || !Number.isFinite(value)) return NULL_TEXT;
  const digits = Number.isInteger(decimals) ? decimals : null;
  return numberFormat(LOCALES[normalizeLang(lang)], digits, digits === null ? 2 : digits).format(value);
}

export function formatPercent(value, lang = "tr", decimals = 1) {
  if (typeof value !== "number" || !Number.isFinite(value)) return NULL_TEXT;
  const code = LOCALES[normalizeLang(lang)];
  const formatter = numberFormat(code, decimals, decimals);
  if (code === "en-US") return `${formatter.format(value)}%`;
  return `${value < 0 ? "-" : ""}%${formatter.format(Math.abs(value))}`;
}

export function formatCell(value, lang = "tr") {
  if (value === null || value === undefined) return NULL_TEXT;
  if (typeof value === "number") return formatNumber(value, lang);
  if (typeof value === "string") return value;
  return String(value);
}

// Sütunun tamamı sayıysa sağ yaslama ve Türkçe biçim var; tek metin hücre bile sütunu metin yapar.
export function isNumericColumn(rows, index) {
  if (!Array.isArray(rows)) return false;
  let seen = false;
  for (const row of rows) {
    const value = Array.isArray(row) ? row[index] : row?.[index];
    if (value === null || value === undefined) continue;
    if (typeof value !== "number" || !Number.isFinite(value)) return false;
    seen = true;
  }
  return seen;
}

// Büyük sayı ölçekle okunur: 12500 → tr "12,5 bin" / en "12.5K". Ölçek adı Türkçede ayrı yazılır.
export function formatCompact(value, lang = "tr") {
  if (typeof value !== "number" || !Number.isFinite(value)) return NULL_TEXT;
  const code = normalizeLang(lang);
  const size = Math.abs(value);
  if (size < COMPACT_MIN) return formatNumber(value, code);
  const [scale, name] = SCALES[code].find(([min]) => size >= min);
  const text = numberFormat(LOCALES[code], 1, 1).format(size / scale);
  return `${value < 0 ? "-" : ""}${text}${code === "en" ? "" : " "}${name}`;
}

// Tarih dilin kısaltmasıyla: "27 Eki 2026" / "Oct 27, 2026". Okunamayan tarih "–"dir, "Invalid Date" değil.
export function formatDate(value, lang = "tr") {
  const date =
    value instanceof Date ? value : new Date(typeof value === "string" || typeof value === "number" ? value : Number.NaN);
  if (Number.isNaN(date.getTime())) return NULL_TEXT;
  const code = LOCALES[normalizeLang(lang)];
  let formatter = DATES.get(code);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat(code, { month: "short", day: "numeric", year: "numeric" });
    DATES.set(code, formatter);
  }
  return formatter.format(date);
}

// Birim kelimeleri dilin: İngilizcede kısaltma noktasız ve boşluklu okunur ("8.3 s").
const SECOND_UNITS = { tr: ["sn", "dk", "sa"], en: ["s", "min", "h"] };

// ASSUMPTION: süre yoksa boş dize döner; durum satırı o zaman süreyi hiç göstermez, "– sn" yazmaz.
export function formatSeconds(seconds, lang = "tr") {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return "";
  const [second, minute, hour] = SECOND_UNITS[normalizeLang(lang)];
  const total = Math.round(seconds);
  const oneDecimal = numberFormat(LOCALES[normalizeLang(lang)], 1, 1);
  if (total < 60) return `${oneDecimal.format(seconds)} ${second}`;
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes < 60) return rest ? `${minutes} ${minute} ${rest} ${second}` : `${minutes} ${minute}`;
  const hours = Math.floor(minutes / 60);
  const leftover = minutes % 60;
  return leftover ? `${hours} ${hour} ${leftover} ${minute}` : `${hours} ${hour}`;
}
