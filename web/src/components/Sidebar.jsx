import { useState } from "react";
import * as api from "../lib/api.js";

// Kenar çubuğu (R5-18): kayıtlı sorular ve geçmiş. Kayıtlı satır soruyu yeniden sorar, geçmiş satırı
// kayıtlı SQL'i modelsiz açar (audit_id ile); kayıtlıda bir de × vardır. Listeler App'ten gelir — ikisinin de ne zaman tazeleneneceği orada bellidir.
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

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

function startOfDay(ms) {
  const day = new Date(ms);
  day.setHours(0, 0, 0, 0);
  return day.getTime();
}

// Kısa Türkçe zaman: "4 dk önce" / "dün". "Dün" takvimsel bir fark, o yüzden gün sayısına
// yerel gecenin başından iniliyor. ASSUMPTION: ts boş ya da okunamazsa boş dize - satır zamansız kalır.
function relativeTime(value, now) {
  if (typeof value !== "string" || !value) return "";
  const then = Date.parse(value);
  if (!Number.isFinite(then)) return "";
  const diff = now - then;
  if (diff < MINUTE) return "şimdi";
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)} dk önce`;
  if (diff < DAY) return `${Math.floor(diff / HOUR)} sa önce`;
  const days = Math.round((startOfDay(now) - startOfDay(then)) / DAY);
  if (days <= 1) return "dün";
  if (days < 7) return `${days} gün önce`;
  if (days < 30) return `${Math.floor(days / 7)} hafta önce`;
  if (days < 365) return `${Math.floor(days / 30)} ay önce`;
  return `${Math.floor(days / 365)} yıl önce`;
}

export default function Sidebar({ saved = [], history = [], onAsk, onRemoved }) {
  const [note, setNote] = useState("");

  const savedRows = list(saved)
    .filter((item) => item?.id != null)
    .map((item) => ({ id: item.id, question: text(item) }))
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
    historyRows.push({
      key: auditId || `h${index}`,
      auditId,
      question,
      status,
      ts: typeof item?.ts === "string" ? item.ts : "",
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
            const time = relativeTime(row.ts, now);
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
