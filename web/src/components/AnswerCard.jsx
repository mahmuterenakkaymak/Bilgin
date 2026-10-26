import { useEffect, useState } from "react";
import * as api from "../lib/api.js";
import { formatNumber, formatSeconds } from "../lib/format.js";
import ChartView from "./ChartView.jsx";
import Evidence from "./Evidence.jsx";
import ResultTable from "./ResultTable.jsx";
import Warnings from "./Warnings.jsx";

const EXPORTS = [
  ["csv", "CSV"],
  ["xlsx", "Excel"],
];

// Kartın kendi özetleri: kullanıcının tabloyu gözle toplamasını önleyen üç sayı. Olguların
// tamamı kanıt panelinde durmaya devam eder; kart yalnız bunları cümlenin altına taşır.
const CHIP_FACTS = ["total", "max", "mean"];

// İndirme geri bildirimi neyin indiğini de söyler: dosyanın kaç satır taşıdığı, ekrandaki
// tablonun satır sayısıdır. Satırı olmayan cevapta sayı uydurulmaz, bugünün adı okunur.
function downloadedLabel(rows) {
  return rows > 0 ? `${formatNumber(rows)} satır indirildi` : "İndirildi";
}

function headFacts(facts) {
  const picked = [];
  for (const name of CHIP_FACTS) {
    const fact = facts.find((item) => item.name === name);
    // Tek hücrelik cevapta üç olgu aynı sayıyı söyler; kartta bir kez okunur.
    if (fact && !picked.some((item) => item.display === fact.display)) picked.push(fact);
  }
  return picked;
}

// Cevap kartı: aynı AskPayload'ın her parçası burada durur — durum satırı, seçilen anlam, cümle,
// uyarılar, tablo, grafiği, indirme ve kayıt düğmeleri, kanıt (R5-18). Kart hiçbir sayıyı yeniden
// hesaplamaz.
// Grafik cevabın parçasıdır: kartın içinde, tablonun altında; `chart` yoksa ChartView kutu açmaz.
export default function AnswerCard({ payload, onSave, choice }) {
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
  // Seçilen anlam: sorunun birden çok okuması varsa hangisiyle koşulduğu cevapta da okunur.
  const chosen = typeof choice === "string" ? choice.trim() : "";
  // Okunur bir okunuşu olmayan olgu karta çıkmaz; panelde zaten kendi satırında duruyor.
  const chips = headFacts(
    (Array.isArray(payload?.facts) ? payload.facts : []).filter((fact) => fact?.label && fact?.display),
  );

  // ASSUMPTION: indirilen sayı kartın elindeki satırlardır — kesik bir sonuçta dosya daha
  // fazlasını taşıyabilir, ama kartın bildiği ekrandaki satır sayısıdır.
  const exportRows = Array.isArray(payload?.rows) ? payload.rows.length : 0;

  // İndirme bir <a>: sekme yer değiştirmediği için tek geri bildirim düğmenin kendisi. Ad 2 sn
  // geri bildirimiyle (sayılıysa sayısıyla) kalır, sonra eski adına döner; kart kapanınca
  // bekleyen sayaç bırakılır.
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
      {chosen && (
        <p id="answer-choice" className="answer-choice">
          Anlam: {chosen}
        </p>
      )}
      {answer && <p id="answer-text" className="answer-text">{answer}</p>}
      <Warnings warnings={payload?.warnings} />
      {chips.length > 0 && (
        <ul id="answer-facts" className="facts answer-facts">
          {chips.map((fact, index) => (
            <li key={`${index}-${fact.name ?? ""}`}>
              <span className="fact-label">{fact.label}</span>
              <span className="fact-value">{fact.display}</span>
            </li>
          ))}
        </ul>
      )}
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
                {downloaded === kind ? downloadedLabel(exportRows) : label}
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
