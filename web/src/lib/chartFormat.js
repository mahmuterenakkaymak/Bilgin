// ECharts seçeneği JSON olarak geldiği için Türkçe sayı biçimi burada işlevle buluşur (PLAN R5-6):
// yalnız biçimleyici eklenir, verinin ve seri tipinin kendisine dokunulmaz.
import { formatNumber, formatPercent } from "./format.js";

const FORMATS = { number: formatNumber, percent: formatPercent };

// Başlığın boyutu kartın ölçeğinden: ECharts'ın varsayılan 18px kalın başlığı kartın içinde büyür.
const TITLE = { fontSize: 14, fontWeight: 600 };

export function withFormatters(option) {
  if (!option || typeof option !== "object") return option;
  // ASSUMPTION: `bilgin` yoksa biçim "number"dır; seçenek yine de Türkçe okunur.
  const format = FORMATS[option.bilgin?.value_format] ?? formatNumber;
  const measure = columnLabel(option.bilgin?.value_column);
  const next = { ...option };
  if (next.tooltip) next.tooltip = { ...next.tooltip, formatter: tooltipFormatter(format, next.tooltip.trigger) };
  for (const key of ["xAxis", "yAxis"]) {
    if (!next[key]) continue;
    const axes = Array.isArray(next[key]) ? next[key] : [next[key]];
    const mapped = axes.map((axis) => withAxisFormatter(axis, format));
    next[key] = Array.isArray(next[key]) ? mapped : mapped[0];
  }
  if (Array.isArray(next.series)) next.series = next.series.map((series) => withLabelFormatter(series, format));
  return withNames(next, measure);
}

// Çizilen şey option'dan okunmalı: başlık ölçü kolonunun adından gelir, ölçüde hiçbir şey yeniden
// hesaplanmaz. Olan bir başlığa dokunulmaz. Sayısal eksen adlandırılmaz: aynı ad başlığın 40 px
// altında ikinci bir ölçü gibi dururdu; ölçü option'da bir kez görünür.
function withNames(option, measure) {
  if (!measure) return option;
  const next = { ...option };
  if (!next.title?.text) next.title = { ...next.title, text: measure, textStyle: TITLE };
  return next;
}

// Kartın tek etiketi: grafik başlığı ile tablonun başlık satırı aynı okunuşu okur (M24 review 4).
// ASSUMPTION: kolon adı ERP'den ASCII gelir; başlık ondan türetilir, Türkçesi uydurulmaz. Büyük
// harfli alias kelimeye döner; içinde küçük harf taşıyan alias zaten elle yazılmış bir addır ve
// olduğundan farklı yazılmaz. Panonun mini tablosu bu görevin dışında.
export function columnLabel(column) {
  const name = String(column ?? "");
  if (!name || /[a-zçğıöşü]/.test(name)) return name;
  const words = name.split("_").filter(Boolean);
  if (!words.length) return "";
  const text = words.join(" ").toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function tooltipFormatter(format, trigger) {
  return (params) => {
    const items = (Array.isArray(params) ? params : [params]).filter(Boolean);
    const rows = items.map((item) => tooltipRow(format, trigger, item));
    if (!rows.length) return "";
    if (!Array.isArray(params)) return rows[0];
    const head = items[0]?.axisValueLabel ?? items[0]?.name;
    return head ? [String(head), ...rows].join("<br/>") : rows.join("<br/>");
  };
}

function tooltipRow(format, trigger, item) {
  const name = trigger === "item" ? item.name || item.seriesName : item.seriesName || item.name;
  return `${item.marker ?? ""}${name ? `${name}: ` : ""}${show(format, item.value)}`;
}

function withAxisFormatter(axis, format) {
  if (!axis || typeof axis !== "object" || axis.type !== "value") return axis;
  return { ...axis, axisLabel: { ...axis.axisLabel, formatter: (value) => show(format, value) } };
}

function withLabelFormatter(series, format) {
  if (!series || typeof series !== "object") return series;
  return { ...series, label: { ...series.label, formatter: (params) => labelFormatter(format, params) } };
}

// Etiket açıkken ad yitirilmesin: pasta dilinin adı biçimli değerin önünde kalır.
function labelFormatter(format, item) {
  const value = show(format, item?.value);
  return item?.name ? `${item.name}: ${value}` : value;
}

function show(format, value) {
  if (Array.isArray(value)) return value.map((item) => show(format, item)).join(", ");
  const number = toNumber(value);
  return number === null ? format(value) : format(number);
}

function toNumber(value) {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && value.trim() && Number.isFinite(Number(value))) return Number(value);
  return null;
}
