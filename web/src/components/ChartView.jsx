import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { useT } from "../i18n/index.js";
import { withFormatters } from "../lib/chartFormat.js";

// Grafiğin renkleri kartın renkleriyle aynı tokenlardan okunur (T222): ECharts'ın varsayılan
// koyu yazısı koyu temada koyu zeminde kalıyor, yani tema değişince option da yeniden boyanmalı.
const TOKENS = { text: "--text", muted: "--muted", line: "--line" };

function palette(node) {
  const style = getComputedStyle(node);
  const colors = {};
  for (const [name, token] of Object.entries(TOKENS)) colors[name] = style.getPropertyValue(token).trim();
  return colors;
}

// Çizilen veri değil, yalnız kalem rengi: eksen çizgisi, eksen ve seri etiketleri, ızgara çizgisi.
function withTheme(option, colors) {
  const next = { ...option, textStyle: { ...option.textStyle, color: colors.text } };
  if (next.title) next.title = { ...next.title, textStyle: { ...next.title.textStyle, color: colors.text } };
  for (const key of ["xAxis", "yAxis"]) {
    const axis = next[key];
    if (!axis) continue;
    next[key] = Array.isArray(axis) ? axis.map((item) => themeAxis(item, colors)) : themeAxis(axis, colors);
  }
  if (Array.isArray(next.series)) next.series = next.series.map((series) => themeSeries(series, colors));
  return next;
}

function themeAxis(axis, colors) {
  if (!axis || typeof axis !== "object") return axis;
  return {
    ...axis,
    axisLine: { ...axis.axisLine, lineStyle: { ...axis.axisLine?.lineStyle, color: colors.line } },
    axisLabel: { ...axis.axisLabel, color: colors.muted },
    nameTextStyle: { ...axis.nameTextStyle, color: colors.muted },
    splitLine: { ...axis.splitLine, lineStyle: { ...axis.splitLine?.lineStyle, color: colors.line } },
  };
}

// Pasta dilinin etiketi ile onu diline bağlayan çizgi de aynı temayı paylaşır.
function themeSeries(series, colors) {
  if (!series || typeof series !== "object") return series;
  return {
    ...series,
    label: { ...series.label, color: colors.text },
    labelLine: { ...series.labelLine, lineStyle: { ...series.labelLine?.lineStyle, color: colors.line } },
  };
}

// Grafiği kod seçer (R5-6): option düz JSON gelir, Türkçe sayı biçimi burada işlevle eklenir;
// burada hiçbir sayı yeniden hesaplanmaz. `chart` yoksa kutu da açılmaz, yer bırakılmaz.
export default function ChartView({ chart }) {
  const { lang, t } = useT();
  const box = useRef(null);

  useEffect(() => {
    if (!box.current) return undefined;
    const instance = echarts.init(box.current);
    const paint = () => instance.setOption(withTheme(withFormatters(chart.option, lang), palette(box.current)));
    paint();
    // ECharts kutuyu açıldığı piksel genişliğinde tutar; kutu pencereden bağımsız daralır
    // (kenar çubuğu dolunca ana sütun kısalır), o yüzden gözlem pencerede değil kutuda.
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(box.current);
    // Tema iki yerden değişir: düğme `html[data-theme]`i yazar, sistem tercihi anahtar yokken
    // kendiliğinden işler. İkisi de tokenları değiştirir, option ise tokenları okur.
    const root = new MutationObserver(paint);
    root.observe(document.documentElement, { attributeFilter: ["data-theme"] });
    const dark = window.matchMedia("(prefers-color-scheme: dark)");
    dark.addEventListener("change", paint);
    return () => {
      observer.disconnect();
      root.disconnect();
      dark.removeEventListener("change", paint);
      instance.dispose();
    };
  }, [chart, lang]);

  // ASSUMPTION: çizilecek seçenek yoksa kutu da açılmaz — boş durumun sözü yoktur, yer bırakılmaz.
  if (!chart?.option) return null;
  return <div id="chart" className="chart" role="img" aria-label={t("chart.label")} ref={box} />;
}
