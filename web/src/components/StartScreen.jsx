import { useEffect, useState } from "react";
import { useT } from "../i18n/index.js";
import * as api from "../lib/api.js";
import AskBox from "./AskBox.jsx";
import StartCard from "./StartCard.jsx";

// Başlangıç ekranı (PLAN R7-21): panonun kartları, altında soru kutusu ve örnek çipler. Kartların
// SQL'i sunucuda yürür — burada hiçbir SQL yoktur ve hiçbir yanıtta SQL okunmaz. Karta tıklamak
// hazır soruyu yeni bir konuşmanın ilk turu olarak açar. Kartlar okunamazsa `onFailed` üstüne
// düşülür: ekran eski boş hâline döner, yani kutu ve çipler her hâlde erişilebilir kalır.
const PLACEHOLDERS = ["bir", "iki", "uc"];

export default function StartScreen({
  examples = [],
  text = "",
  onChange,
  onAsk,
  onReapprove,
  onFailed,
  isAdmin = false,
  loading = false,
  datasetKey = 0,
}) {
  const { t } = useT();
  const [cards, setCards] = useState(null); // null: henüz okunmadı — yerinde iskelet kartlar boyanır

  // Kartlar kümenin sorularıdır: küme değişince liste baştan okunur, yoksa eski veritabanının
  // sayıları yeni kümenin üstünde kalır.
  useEffect(() => {
    let mounted = true;
    api
      .start()
      .then((data) => mounted && setCards(Array.isArray(data?.cards) ? data.cards : []))
      .catch(() => {
        if (mounted) onFailed?.();
      });
    return () => {
      mounted = false;
    };
  }, [datasetKey]);

  // "Yenile" tek kartın yükünü geri getirir: liste yerinde değişir, ekran baştan okunmaz.
  const refresh = async (card) => {
    const data = await api.startRefresh(card.id);
    if (!data?.card) return;
    setCards((list) => (Array.isArray(list) ? list.map((item) => (item?.id === card.id ? data.card : item)) : list));
  };

  // "Panodan çıkar" yalnız kişinin kendi kartındadır: silme kabul edilirse kart listeden yerinde
  // düşer — ekran baştan okunmaz ve hiçbir konuşma açılmaz.
  const unpin = async (card) => {
    await api.unpinCard(card.id);
    setCards((list) => (Array.isArray(list) ? list.filter((item) => item?.id !== card.id) : list));
  };

  // Açma sunucuda kayıtlı SQL'i yürütür ve turu yeni bir konuşmanın 1. turu yazar; adres o
  // konuşmayı okur, yani kartın cevabı akışın kendisinden gelir.
  const open = async (card) => {
    const payload = await api.startOpen(card.id);
    if (payload?.conversation_id) window.location.hash = `#/c/${payload.conversation_id}`;
  };

  const list = Array.isArray(cards) ? cards : [];

  return (
    <section className="screen ask-flow">
      <div id="start" className="start-grid">
        {cards === null &&
          PLACEHOLDERS.map((key) => (
            <div className="card start-card skeleton" key={key} aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
          ))}
        {list.map((card) => (
          <StartCard
            key={card?.id}
            card={card}
            isAdmin={isAdmin}
            onOpen={open}
            onRefresh={refresh}
            onReapprove={onReapprove}
            onUnpin={unpin}
          />
        ))}
      </div>
      {cards !== null && list.length === 0 && (
        <p className="start-empty" id="start-empty">
          {t("start.empty")}
          {isAdmin && (
            <>
              {t("start.empty.adminBefore")}
              <a href="#/hazir-sorular">{t("nav.ready")}</a>
              {t("start.empty.adminAfter")}
            </>
          )}
        </p>
      )}
      <AskBox value={text} onChange={onChange} onAsk={onAsk} loading={loading} examples={examples} />
    </section>
  );
}
