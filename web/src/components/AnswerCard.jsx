import { useEffect, useState } from "react";
import * as api from "../lib/api.js";
import { formatSeconds } from "../lib/format.js";
import ChartView from "./ChartView.jsx";
import Evidence from "./Evidence.jsx";
import ResultTable from "./ResultTable.jsx";
import Warnings from "./Warnings.jsx";

const EXPORTS = [
  ["csv", "CSV"],
  ["xlsx", "Excel"],
];

// Cevap kartı: aynı AskPayload'ın her parçası burada durur — durum satırı, cümle, uyarılar,
// tablo, grafiği, indirme ve kayıt düğmeleri, kanıt (R5-18). Kart hiçbir sayıyı yeniden hesaplamaz.
// Grafik cevabın parçasıdır: kartın içinde, tablonun altında; `chart` yoksa ChartView kutu açmaz.
export default function AnswerCard({ payload, onSave }) {
  const [phase, setPhase] = useState("idle"); // idle | saving | saved | error
  const [note, setNote] = useState("");
  const [downloaded, setDownloaded] = useState(""); // "" | csv | xlsx

  const answer = typeof payload?.answer_text === "string" ? payload.answer_text : "";
  const mode = typeof payload?.mode === "string" ? payload.mode : "";
  const seconds = payload?.timings?.total_s;
  // Tek ondalık basamak 0,04 saniyeyi "0,0 sn" yapar; okunur bir süre değildir, yazılmaz.
  const elapsed = typeof seconds === "number" && seconds >= 0.05 ? formatSeconds(seconds) : "";
  const auditId = typeof payload?.audit_id === "string" ? payload.audit_id : "";
  const save = onSave ?? api.savedAdd;
  const status = ["✓ Cevaplandı", mode, elapsed].filter(Boolean).join(" · ");

  // İndirme bir <a>: sekme yer değiştirmediği için tek geri bildirim düğmenin kendisi. Ad 2 sn
  // "İndirildi" kalır, sonra eski adına döner; kart kapanırsa bekleyen sayaç bırakılır.
  useEffect(() => {
    if (!downloaded) return undefined;
    const timer = setTimeout(() => setDownloaded(""), 2000);
    return () => clearTimeout(timer);
  }, [downloaded]);

  const saveQuestion = async () => {
    setPhase("saving");
    setNote("");
    try {
      await save({ question: payload?.question ?? "", mode: payload?.mode ?? null, sql: payload?.sql || null });
      setPhase("saved");
    } catch (error) {
      setPhase("error");
      setNote(error?.message || "Soru kaydedilemedi.");
    }
  };

  return (
    <section id="answer-card" className="card answer-card">
      <p className="answer-status">{status}</p>
      {answer && <p id="answer-text" className="answer-text">{answer}</p>}
      <Warnings warnings={payload?.warnings} />
      <ResultTable
        columns={payload?.columns}
        rows={payload?.rows}
        rowCount={payload?.row_count}
        truncated={Boolean(payload?.truncated)}
      />
      <ChartView chart={payload?.chart} />
      <div className="answer-actions">
        {auditId && (
          <>
            <span className="answer-actions-label">Tamamını indir:</span>
            {EXPORTS.map(([kind, label]) => (
              <a
                key={kind}
                className={downloaded === kind ? "btn btn-downloaded" : "btn"}
                id={`export-${kind}`}
                href={api.exportUrl(auditId, kind)}
                onClick={() => setDownloaded(kind)}
              >
                {downloaded === kind ? "İndirildi" : label}
              </a>
            ))}
          </>
        )}
        <button
          type="button"
          id="save-question"
          className="btn"
          onClick={saveQuestion}
          disabled={phase === "saving" || phase === "saved"}
        >
          {phase === "saving" ? "Kaydediliyor…" : phase === "saved" ? "Kaydedildi" : "Soruyu kaydet"}
        </button>
        {phase === "error" && <span className="answer-note">{note}</span>}
      </div>
      <Evidence payload={payload} />
    </section>
  );
}
