// Ekrana çıkan her sayının tek kaynağı: Python tarafındaki report/fmt.py ile aynı okunuş.
// Binlik ayıracı nokta, ondalık virgül, yüzde işareti sayının önünde; boş hücre "0" değil "–".
const NULL_TEXT = "–";

const GROUPED = new Intl.NumberFormat("tr-TR", { maximumFractionDigits: 2 });
const ONE_DECIMAL = new Intl.NumberFormat("tr-TR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export function formatNumber(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return NULL_TEXT;
  return GROUPED.format(value);
}

export function formatPercent(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return NULL_TEXT;
  return `${value < 0 ? "-" : ""}%${ONE_DECIMAL.format(Math.abs(value))}`;
}

export function formatCell(value) {
  if (value === null || value === undefined) return NULL_TEXT;
  if (typeof value === "number") return formatNumber(value);
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

// ASSUMPTION: süre yoksa boş dize döner; durum satırı o zaman süreyi hiç göstermez, "– sn" yazmaz.
export function formatSeconds(seconds) {
  if (typeof seconds !== "number" || !Number.isFinite(seconds) || seconds < 0) return "";
  const total = Math.round(seconds);
  if (total < 60) return `${ONE_DECIMAL.format(seconds)} sn`;
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes < 60) return rest ? `${minutes} dk ${rest} sn` : `${minutes} dk`;
  const hours = Math.floor(minutes / 60);
  const leftover = minutes % 60;
  return leftover ? `${hours} sa ${leftover} dk` : `${hours} sa`;
}
