import { useState } from "react";
import { formatCell, isNumericColumn } from "../lib/format.js";
import { cardValueText, refreshedText } from "../lib/startCards.js";
import ChartView from "./ChartView.jsx";

// Panonun tek kartı (PLAN R7-21): başlık, yükü (sayı / küçük grafik / mini tablo), yenilenme
// yazısı, "Yenile" ve kişisel kartın "Panodan çıkar"ı. Karta tıklamak hazır soruyu yeni bir
// konuşma olarak açar; kartın kendi düğmeleri tıklamayı yuttuğu için yenilemek konuşma açmaz.
// Yürütme hatası kartın kendi cümlesidir ve err tokenlarıyla boyanır — yönetici orada soruyu
// soru kutusuna alabilir.

// Mini tablo: kartın kutusu kadar. Satırlar sunucuda kesilir (CARD_TABLE_ROWS); burada hiçbir
// sayı yeniden hesaplanmaz, sütun yalnız Türkçe okunur.
function MiniTable({ columns, rows }) {
  const names = Array.isArray(columns) ? columns : [];
  const list = Array.isArray(rows) ? rows : [];
  if (!names.length || !list.length) return <p className="start-card-empty">Bu soruya uyan kayıt yok.</p>;
  const numeric = names.map((_, index) => isNumericColumn(list, index));

  return (
    <div className="table-wrap start-card-table">
      <table className="result-table">
        <thead>
          <tr>
            {names.map((name, index) => (
              <th key={`${index}-${name}`} scope="col" className={numeric[index] ? "num" : undefined}>
                {name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {list.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {names.map((_, index) => (
                <td key={index} className={numeric[index] ? "num" : undefined}>
                  {formatCell(row?.[index])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Kartın yükü üç biçimden biridir; hiçbirinde eksik alan ekrana "undefined" düşmez.
function CardLoad({ card }) {
  if (card.error) return <p className="error-reason start-card-error-text">{card.error}</p>;
  if (card.display === "number") {
    const label = typeof card.label === "string" ? card.label.trim() : "";
    return (
      <div className="result-single start-card-number">
        <span className="result-single-value start-card-value">{cardValueText(card)}</span>
        {label && <span className="result-single-label start-card-label">{label}</span>}
      </div>
    );
  }
  if (card.display === "chart") {
    // Sözleşmede `chart` seçenekli: yük gelmediyse kart boş bir kutu değil, nedenini söyleyen karttır.
    if (!card.chart?.option) return <p className="start-card-empty">Kartın grafiği yüklenemedi.</p>;
    return (
      <div className="start-card-chart">
        <ChartView chart={card.chart} />
      </div>
    );
  }
  return <MiniTable columns={card.columns} rows={card.rows} />;
}

export default function StartCard({ card, isAdmin = false, onOpen, onRefresh, onReapprove, onUnpin }) {
  const [busy, setBusy] = useState(""); // "" | "open" | "refresh" | "unpin"
  const [note, setNote] = useState("");

  const title = String(card?.title ?? "").trim() || String(card?.question ?? "").trim();
  const refreshed = card ? refreshedText(card.refreshed_at) : "";

  // Açma ve yenileme aynı iki durumun iki işi: meşgule ikinci tıklama işlemez, red cümle olur.
  const open = async () => {
    if (busy) return;
    setBusy("open");
    setNote("");
    try {
      await onOpen?.(card);
    } catch (error) {
      setBusy("");
      setNote(error?.message || "Kart açılamadı.");
    }
  };

  const refresh = async () => {
    if (busy) return;
    setBusy("refresh");
    setNote("");
    try {
      await onRefresh?.(card);
    } catch (error) {
      // 429'un cümlesi sunucunundur: "Bu kart az önce yenilendi; 12 sn sonra yeniden deneyin."
      setNote(error?.message || "Kart yenilenemedi.");
    }
    setBusy("");
  };

  // Kişisel kartı panodan çıkarmak kartı listeden düşürür: başarılı çağrıda kart zaten gider,
  // o yüzden meşgul durumu geri alınmaz. Reddin cümlesi (404/409) sunucunundur.
  const unpin = async () => {
    if (busy) return;
    setBusy("unpin");
    setNote("");
    try {
      await onUnpin?.(card);
    } catch (error) {
      setBusy("");
      setNote(error?.message || "Kart panodan çıkarılamadı.");
    }
  };

  const click = (event) => {
    if (event.target.closest("button")) return; // düğme kendi işini görür, kart açılmaz
    open();
  };

  const key = (event) => {
    if (event.target !== event.currentTarget || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    open();
  };

  const error = Boolean(card?.error);

  return (
    <article
      className={error ? "card start-card start-card-error error-card" : "card start-card"}
      data-card-id={card?.id}
      data-display={card?.display ?? "table"}
      role="button"
      tabIndex={0}
      aria-label={`${title || "Kart"} — konuşma olarak aç`}
      title={card?.question || undefined}
      onClick={click}
      onKeyDown={key}
    >
      <h2 className={error ? "start-card-title error-title" : "start-card-title"}>{title}</h2>
      <CardLoad card={card} />
      <div className="start-card-actions">
        {refreshed && <span className="start-card-meta">{refreshed} yenilendi</span>}
        <button
          type="button"
          className="btn btn-ghost start-card-refresh"
          data-card-refresh={card?.id}
          disabled={Boolean(busy)}
          onClick={refresh}
        >
          {busy === "refresh" ? "Yenileniyor…" : "Yenile"}
        </button>
        {card?.personal && (
          <button
            type="button"
            className="start-card-unpin"
            data-card-unpin={card?.id}
            disabled={Boolean(busy)}
            onClick={unpin}
          >
            {busy === "unpin" ? "Çıkarılıyor…" : "Panodan çıkar"}
          </button>
        )}
        {error && isAdmin && (
          <button
            type="button"
            className="btn start-card-reapprove"
            data-card-reapprove={card?.id}
            disabled={Boolean(busy)}
            onClick={() => onReapprove?.(card)}
          >
            SQL'i yeniden onayla
          </button>
        )}
      </div>
      {busy === "open" && <p className="start-card-note" role="status">Kart açılıyor…</p>}
      {note && <p className="start-card-note" role="alert">{note}</p>}
    </article>
  );
}
