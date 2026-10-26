import TurnCard from "./TurnCard.jsx";

// Konuşmanın akışı (R7-15): her tur kendi soru balonu ve kartıyla bir satırdır; en alttaki soru
// kutusu App'te durur, burada yalnız turlar akar. Kartın kendisi TurnCard'da çözülür.
// `reapproveId` bir kartın "SQL'i yeniden onayla"sından gelen cevabın kartıdır (R7-21) ve o
// bağlantı yalnız son turda okunur — eski bir turun cevabı güncellemenin kaynağı olamaz.
export default function Thread({
  turns,
  onExpand,
  onReplay,
  onChoose,
  onChange,
  onSave,
  isAdmin = false,
  reapproveId = null,
}) {
  const list = Array.isArray(turns) ? turns : [];
  return (
    <section id="thread" className="thread">
      {list.map((turn, index) => {
        const question = String(turn?.question ?? "").trim();
        return (
          <article className="turn" key={index}>
            {question && <p className="turn-question">{question}</p>}
            <TurnCard
              turn={turn}
              onExpand={onExpand}
              onReplay={onReplay}
              onChoose={onChoose}
              onChange={onChange}
              onSave={onSave}
              isAdmin={isAdmin}
              reapproveId={index === list.length - 1 ? reapproveId : null}
            />
          </article>
        );
      })}
    </section>
  );
}
