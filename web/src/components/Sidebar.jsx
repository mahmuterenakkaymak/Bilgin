import { useState } from "react";
import * as api from "../lib/api.js";

// Kenar çubuğu (R5-18): kayıtlı sorular ve geçmiş. Her satır soruyu yeniden sorar, kayıtlıda
// bir de × vardır. Listeler App'ten gelir — ikisinin de ne zaman tazeleneneceği orada bellidir.
// ASSUMPTION: geçmiş /api/history'den geldiği sırayla (en yeni önce) gösterilir; sözleşme sırayı üreticide veriyor.
const EMPTY_SAVED = "Henüz kayıtlı soru yok.";
const EMPTY_HISTORY = "Geçmiş boş.";

function list(value) {
  return Array.isArray(value) ? value : [];
}

function text(item) {
  return String(item?.question ?? "").trim();
}

// Cevaplanan ✓, netleştirme bekleyen ?, kalan her şey ✗: geçmişin tek göstergesi durum alanı.
function marker(status) {
  if (status === "answered") return { glyph: "✓", tone: "ok" };
  if (status === "needs_clarification") return { glyph: "?", tone: "warn" };
  return { glyph: "✗", tone: "err" };
}

export default function Sidebar({ saved = [], history = [], onAsk, onRemoved }) {
  const [note, setNote] = useState("");

  const savedRows = list(saved)
    .filter((item) => item?.id != null)
    .map((item) => ({ id: item.id, question: text(item) }))
    .filter((row) => row.question);
  const historyRows = list(history)
    .map((item, index) => ({
      key: typeof item?.audit_id === "string" && item.audit_id ? item.audit_id : `h${index}`,
      question: text(item),
      status: item?.status,
    }))
    .filter((row) => row.question);

  const remove = async (id) => {
    try {
      await api.savedRemove(id);
      setNote("");
      onRemoved?.();
    } catch (error) {
      setNote(error?.message || "Kayıt silinemedi.");
    }
  };

  return (
    <>
      <section className="side-block">
        <h2 className="side-title">Kayıtlı sorular</h2>
        {note && <p className="side-note">{note}</p>}
        <ul id="saved-list" className="side-list">
          {savedRows.length === 0 && <li className="side-empty">{EMPTY_SAVED}</li>}
          {savedRows.map((row) => (
            <li className="side-item" key={row.id}>
              <button type="button" className="side-text" title={row.question} onClick={() => onAsk?.(row.question)}>
                <span className="side-label">{row.question}</span>
              </button>
              <button
                type="button"
                className="side-remove"
                aria-label="Kaydı sil"
                title="Kaydı sil"
                onClick={() => remove(row.id)}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      </section>
      <section className="side-block">
        <h2 className="side-title">Geçmiş</h2>
        <ul id="history-list" className="side-list">
          {historyRows.length === 0 && <li className="side-empty">{EMPTY_HISTORY}</li>}
          {historyRows.map((row) => {
            const { glyph, tone } = marker(row.status);
            return (
              <li className="side-item" key={row.key}>
                <button type="button" className="side-text" title={row.question} onClick={() => onAsk?.(row.question)}>
                  <span className={`side-marker marker-${tone}`} aria-hidden="true">
                    {glyph}
                  </span>
                  <span className="side-label">{row.question}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </section>
    </>
  );
}
