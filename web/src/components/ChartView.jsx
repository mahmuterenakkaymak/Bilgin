import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { withFormatters } from "../lib/chartFormat.js";

// Grafiği kod seçer (R5-6): option düz JSON gelir, Türkçe sayı biçimi burada işlevle eklenir;
// burada hiçbir sayı yeniden hesaplanmaz. `chart` yoksa kutu da açılmaz, yer bırakılmaz.
export default function ChartView({ chart }) {
  const box = useRef(null);

  useEffect(() => {
    if (!box.current) return undefined;
    const instance = echarts.init(box.current);
    instance.setOption(withFormatters(chart.option));
    // ECharts kutuyu açıldığı piksel genişliğinde tutar; kutu pencereden bağımsız daralır
    // (kenar çubuğu dolunca ana sütun kısalır), o yüzden gözlem pencerede değil kutuda.
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(box.current);
    return () => {
      observer.disconnect();
      instance.dispose();
    };
  }, [chart]);

  if (!chart?.option) return null;
  return <div id="chart" className="chart" ref={box} />;
}
