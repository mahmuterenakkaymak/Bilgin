import { useEffect, useState } from "react";
import * as api from "../lib/api.js";
import { chipFacts } from "../lib/facts.js";
import { formatNumber, formatSeconds } from "../lib/format.js";
import { suggestDisplay } from "../lib/startCards.js";
import ChartView from "./ChartView.jsx";
import Evidence from "./Evidence.jsx";
import ReadyQuestionForm from "./ReadyQuestionForm.jsx";
import ResultTable from "./ResultTable.jsx";
import Warnings from "./Warnings.jsx";

const EXPORTS = [
  ["csv", "CSV"],
  ["xlsx", "Excel"],
];

// Panoya ekleme ve yeniden onay aynı iki durumun iki işidir: meşgule ikinci tıklama işlemez,
// reddin cümlesi düğmenin yanında okunur.
const IDLE = { phase: "idle", note: "" };

// İndirme geri bildirimi neyin indiğini de söyler: dosyanın kaç satır taşıdığı, ekrandaki
// tablonun satır sayısıdır. Satırı olmayan cevapta sayı uydurulmaz, bugünün adı okunur.
function downloadedLabel(rows) {
  return rows > 0 ? `${formatNumber(rows)} satır indirildi` : "İndirildi";
}

// Cevap kartı: aynı AskPayload'ın her parçası burada durur — durum satırı, seçilen anlam, cümle,
// uyarılar, tablo, grafiği, indirme ve kayıt düğmeleri, kanıt (R5-18). Kart hiçbir sayıyı yeniden
// hesaplamaz.
// Grafik cevabın parçasıdır: kartın içinde, tablonun altında; `chart` yoksa ChartView kutu açmaz.
// Panonun tarafları (R7-21): "Panoma ekle" cevabı kişinin kendi kartı yapar, "Hazır soru yap"
// yöneticiye formu açar. `reapproveId` yalnız bir kartın "SQL'i yeniden onayla"sından gelmiştir
// — yani yöneticinin yolundan — ve o zaman formun yerine geçen "Bu SQL ile güncelle" durur.
export default function AnswerCard({ payload, onSave, choice, isAdmin = false, reapproveId = null }) {
  const [phase, setPhase] = useState("idle"); // idle | saving | saved | error
  const [note, setNote] = useState("");
  const [downloaded, setDownloaded] = useState(""); // "" | csv | xlsx
  const [pin, setPin] = useState(IDLE); // panoya ekleme
  const [reapprove, setReapprove] = useState(IDLE); // kartın SQL'ini bu cevapla güncelleme
  const [readyOpen, setReadyOpen] = useState(false);

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
  // Kartın çip şeridi cevabın üç özeti; çipe girmeyen olgular kanıt panelinin altında listelenir.
  const chips = chipFacts(payload?.facts);

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

  // Panoya ekleme bir kişisel karttır ve yükü bu cevabın kaydıdır: SQL gönderilmez, sunucu onu
  // `audit_id`den alır (R7-17). Kotanın 409'u kendi cümlesiyle döner — uydurulmuş bir yazı değil.
  const pinCard = async () => {
    setPin({ phase: "saving", note: "" });
    try {
      await api.pinCard({ audit_id: auditId });
      setPin({ phase: "done", note: "" });
    } catch (error) {
      setPin({ phase: "error", note: error?.message || "Kart panoya eklenemedi." });
    }
  };

  // Kartın yürümeyen SQL'i bu cevapla değiştirilir. Görünüm de birlikte söylenir: PUT `display`i
  // kendiliğinden yeniden hesaplamaz, yoksa sayı olan yeni sonuç kartta mini tablo olarak kalırdı.
  const reapproveCard = async () => {
    setReapprove({ phase: "saving", note: "" });
    try {
      await api.readyUpdate(reapproveId, { audit_id: auditId, display: suggestDisplay(payload) });
      setReapprove({ phase: "done", note: "" });
    } catch (error) {
      setReapprove({ phase: "error", note: error?.message || "Kart güncellenemedi." });
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
          <div className="answer-exports">
            <span className="answer-actions-label">Tamamını indir:</span>
            <span className="answer-export-pair">
              {EXPORTS.map(([kind, label]) => (
                <a
                  key={kind}
                  className={`answer-export${downloaded === kind ? " btn-downloaded" : ""}`}
                  id={`export-${kind}`}
                  href={api.exportUrl(auditId, kind)}
                  onClick={() => setDownloaded(kind)}
                >
                  {downloaded === kind ? downloadedLabel(exportRows) : label}
                </a>
              ))}
            </span>
          </div>
        )}
        <div className="answer-workflow">
          <button
            type="button"
            id="save-question"
            className={`answer-action${phase === "saved" ? " answer-action-done" : ""}`}
            onClick={saveQuestion}
            disabled={phase === "saving" || phase === "saved"}
          >
            {phase === "saving" ? "Kaydediliyor…" : phase === "saved" ? "Kaydedildi" : "Soruyu kaydet"}
          </button>
          {phase === "error" && <span className="answer-note">{note}</span>}
          {auditId && (
            <button
              type="button"
              id="pin-card"
              className={`answer-action${pin.phase === "done" ? " answer-action-done" : ""}`}
              onClick={pinCard}
              disabled={pin.phase === "saving" || pin.phase === "done"}
            >
              {pin.phase === "saving" ? "Ekleniyor…" : pin.phase === "done" ? "Panoya eklendi" : "Panoma ekle"}
            </button>
          )}
          {pin.phase === "error" && <span className="answer-note">{pin.note}</span>}
          {reapproveId && auditId && (
            <button
              type="button"
              id="ready-reapprove"
              className={`answer-action${reapprove.phase === "done" ? " answer-action-done" : ""}`}
              onClick={reapproveCard}
              disabled={reapprove.phase === "saving" || reapprove.phase === "done"}
            >
              {reapprove.phase === "saving"
                ? "Güncelleniyor…"
                : reapprove.phase === "done"
                  ? "Kart güncellendi"
                  : "Bu SQL ile güncelle"}
            </button>
          )}
          {reapprove.phase === "error" && <span className="answer-note">{reapprove.note}</span>}
          {isAdmin && auditId && !reapproveId && !readyOpen && (
            <button type="button" id="make-ready" className="answer-action" onClick={() => setReadyOpen(true)}>
              Hazır soru yap
            </button>
          )}
        </div>
      </div>
      {readyOpen && <ReadyQuestionForm payload={payload} onCancel={() => setReadyOpen(false)} />}
      <Evidence payload={payload} />
    </section>
  );
}
