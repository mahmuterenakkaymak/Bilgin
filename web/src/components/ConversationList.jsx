import { useState } from "react";
import * as api from "../lib/api.js";

// Konuşma listesi (PLAN R7-15): geçmişin üstünde, her satırı bir konuşma. Satıra gelmek hiçbir SQL
// koşturmaz - adresi #/c/<id> yapar, turları AskScreen conversationGet ile okur. Silme onay ister.
// ASSUMPTION: satırın zamanı en son güncellenme (updated_at); konuşma listesi de üreticide bu alana
// göre sıralanıyor, böylece satırdaki zaman ile sıra aynı gerçeği söyler.
const EMPTY = "Henüz konuşma yok.";
const DELETE_QUESTION = "Konuşma silinsin mi?";

// Tur sayısını iki satır da okur (KONUŞMALAR ve GEÇMİŞ): cümle burada, iki satır aynı kaynaktan yazar.
export function turnLabel(turns) {
  return `${turns} tur`;
}

function list(value) {
  return Array.isArray(value) ? value : [];
}

function text(item) {
  return String(item?.title ?? "").trim();
}

// Satır en son sorulan soruyla adlanır (M26 review 4): birkaç konuşma aynı ilk soruyla açılıyor ve
// defter birbirinin aynısı satırlara iniyordu. `last_question`u App birleştirir; gelmeyince satır
// ilk sorusuyla kalır.
function lastQuestion(item) {
  return String(item?.last_question ?? "").trim();
}

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

function startOfDay(ms) {
  const day = new Date(ms);
  day.setHours(0, 0, 0, 0);
  return day.getTime();
}

// Kısa Türkçe zaman: "4 dk önce" / "dün". Boş ya da okunamaz zamanda boş dize - satır zamansız kalır.
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

export default function ConversationList({ conversations = [], onRemoved }) {
  const [note, setNote] = useState("");

  const rows = list(conversations)
    .filter((item) => item?.id != null)
    .map((item) => ({
      id: item.id,
      title: text(item),
      last: lastQuestion(item),
      updated: typeof item?.updated_at === "string" ? item.updated_at : "",
      turns: Number.isFinite(item?.turns) ? item.turns : 0,
    }));
  const now = Date.now();

  // Satır yalnız adrese yazır: ask/replay çağırmaz, konuşmayı açmak turları GET ile okur.
  const open = (id) => {
    window.location.hash = `#/c/${encodeURIComponent(id)}`;
  };

  const remove = async (id) => {
    if (!window.confirm(DELETE_QUESTION)) return;
    try {
      await api.conversationDelete(id);
      setNote("");
      onRemoved?.(id);
    } catch (error) {
      setNote(error?.message || "Konuşma silinemedi.");
    }
  };

  return (
    <section className="side-block">
      <h2 className="side-title">Konuşmalar</h2>
      {note && <p className="side-note">{note}</p>}
      <ul id="conversation-list" className="side-list side-scroll">
        {rows.length === 0 && <li className="side-empty">{EMPTY}</li>}
        {rows.map((row) => {
          const time = relativeTime(row.updated, now);
          const first = row.title || "Cevapsız konuşma";
          const label = row.last || first;
          return (
            <li className="side-item" key={row.id}>
              <button type="button" className="side-text" title={first} onClick={() => open(row.id)}>
                {time && <span className="side-time">{time}</span>}
                <span className="side-label">{label}</span>
                <span className="side-count">{turnLabel(row.turns)}</span>
              </button>
              <button
                type="button"
                className="side-remove"
                data-conversation-delete={row.id}
                aria-label="Konuşmayı sil"
                title="Konuşmayı sil"
                onClick={() => remove(row.id)}
              >
                ×
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
