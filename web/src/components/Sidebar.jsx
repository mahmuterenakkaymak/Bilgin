import { useState } from "react";
import { useT } from "../i18n/index.js";
import * as api from "../lib/api.js";
import { relativeTime } from "../lib/time.js";
import ConversationList, { turnLabel } from "./ConversationList.jsx";

// Kenar çubuğu (R5-18): kayıtlı sorular ve geçmiş. Kayıtlı satır soruyu yeniden sorar, geçmiş satırı
// kayıtlı SQL'i modelsiz açar (audit_id ile); kayıtlıda bir de × vardır. Listeler App'ten gelir — ikisinin de ne zaman tazeleneneceği orada bellidir.
// Cümleler kataloğunda (R8-19); satırların kendisi veridir, çevrilmez.
// ASSUMPTION: geçmiş /api/history'den geldiği sırayla (en yeni önce) gösterilir; sözleşme sırayı üreticide veriyor.
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

export default function Sidebar({ saved = [], history = [], conversations = [], onAsk, onRemoved }) {
  const { t } = useT();
  const [note, setNote] = useState("");

  const savedRows = list(saved)
    .filter((item) => item?.id != null)
    .map((item) => ({
      id: item.id,
      question: text(item),
      created: typeof item?.created_at === "string" ? item.created_at : "",
    }))
    .filter((row) => row.question);
  // Ardışık aynı soru + durum tek satıra toplanır: bir demo turu geçmişi yedi klon satırla doldurmasın.
  const historyRows = [];
  for (const [index, item] of list(history).entries()) {
    const question = text(item);
    if (!question) continue;
    const status = item?.status;
    const previous = historyRows[historyRows.length - 1];
    if (previous && previous.question === question && previous.status === status) {
      previous.count += 1;
      continue;
    }
    const auditId = typeof item?.audit_id === "string" && item.audit_id ? item.audit_id : "";
    // Konuşmayla koşan soru kaçıncı tur olduğunu taşır: satır "n tur" ile hangi tur olduğunu söyler.
    const conversationId = typeof item?.conversation_id === "string" && item.conversation_id ? item.conversation_id : "";
    const turn = conversationId && Number.isFinite(item?.turn) ? item.turn : null;
    historyRows.push({
      key: auditId || `h${index}`,
      auditId,
      question,
      status,
      ts: typeof item?.ts === "string" ? item.ts : "",
      turn,
      count: 1,
    });
  }
  const now = Date.now();

  const remove = async (id) => {
    try {
      await api.savedRemove(id);
      setNote("");
      onRemoved?.();
    } catch (error) {
      setNote(error?.message || t("side.saved.deleteFailed"));
    }
  };

  return (
    <>
      <section className="side-block">
        <h2 className="side-title">{t("side.saved.title")}</h2>
        {note && <p className="side-note">{note}</p>}
        <ul id="saved-list" className="side-list">
          {savedRows.length === 0 && <li className="side-empty">{t("side.saved.empty")}</li>}
          {savedRows.map((row) => {
            const time = relativeTime(row.created, now, t);
            return (
              <li className="side-item" key={row.id}>
                <button type="button" className="side-text" title={row.question} onClick={() => onAsk?.(row.question)}>
                  {time && <span className="side-time">{time}</span>}
                  <span className="side-label">{row.question}</span>
                </button>
                <button
                  type="button"
                  className="side-remove"
                  aria-label={t("side.saved.delete")}
                  title={t("side.saved.delete")}
                  onClick={() => remove(row.id)}
                >
                  ×
                </button>
              </li>
            );
          })}
        </ul>
      </section>
      <ConversationList conversations={conversations} onRemoved={onRemoved} />
      <section className="side-block">
        <h2 className="side-title">{t("side.history.title")}</h2>
        <ul id="history-list" className="side-list side-scroll">
          {historyRows.length === 0 && <li className="side-empty">{t("side.history.empty")}</li>}
          {historyRows.map((row) => {
            const { glyph, tone } = marker(row.status);
            const time = relativeTime(row.ts, now, t);
            return (
              <li className="side-item" key={row.key}>
                <button
                  type="button"
                  className="side-text"
                  title={row.question}
                  onClick={() => onAsk?.(row.question, row.auditId || null)}
                >
                  <span className={`side-marker marker-${tone}`} aria-hidden="true">
                    {glyph}
                  </span>
                  {time && <span className="side-time">{time}</span>}
                  <span className="side-label">{row.question}</span>
                  {row.turn != null && <span className="side-turn">{turnLabel(row.turn, t)}</span>}
                  {row.count > 1 && <span className="side-count">×{row.count}</span>}
                </button>
              </li>
            );
          })}
        </ul>
      </section>
    </>
  );
}
