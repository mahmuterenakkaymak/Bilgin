import { useState } from "react";
import { useT } from "../i18n/index.js";
import * as api from "../lib/api.js";
import { relativeTime } from "../lib/time.js";

// Konuşma listesi (PLAN R7-15): geçmişin üstünde, her satırı bir konuşma. Satıra gelmek hiçbir SQL
// koşturmaz - adresi #/c/<id> yapar, turları AskScreen conversationGet ile okur. Silme onay ister.
// Cümleler kataloğunda (R8-19); başlıklar ve sorular veridir, çevrilmez.
// ASSUMPTION: satırın zamanı en son güncellenme (updated_at); konuşma listesi de üreticide bu alana
// göre sıralanıyor, böylece satırdaki zaman ile sıra aynı gerçeği söyler.

// Tur sayısını iki satır da okur (KONUŞMALAR ve GEÇMİŞ): cümle katalogda, iki satır aynı kaynaktan yazar.
export function turnLabel(turns, t) {
  return t(turns === 1 ? "side.turns.one" : "side.turns", { count: turns });
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

export default function ConversationList({ conversations = [], onRemoved }) {
  const { t } = useT();
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
    if (!window.confirm(t("side.conversations.deleteConfirm"))) return;
    try {
      await api.conversationDelete(id);
      setNote("");
      onRemoved?.(id);
    } catch (error) {
      setNote(error?.message || t("side.conversations.deleteFailed"));
    }
  };

  return (
    <section className="side-block">
      <h2 className="side-title">{t("side.conversations.title")}</h2>
      {note && <p className="side-note">{note}</p>}
      <ul id="conversation-list" className="side-list side-scroll">
        {rows.length === 0 && <li className="side-empty">{t("side.conversations.empty")}</li>}
        {rows.map((row) => {
          const time = relativeTime(row.updated, now, t);
          const first = row.title || t("side.conversations.untitled");
          const label = row.last || first;
          return (
            <li className="side-item" key={row.id}>
              <button type="button" className="side-text" title={first} onClick={() => open(row.id)}>
                {time && <span className="side-time">{time}</span>}
                <span className="side-label">{label}</span>
                <span className="side-count">{turnLabel(row.turns, t)}</span>
              </button>
              <button
                type="button"
                className="side-remove"
                data-conversation-delete={row.id}
                aria-label={t("side.conversations.delete")}
                title={t("side.conversations.delete")}
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
