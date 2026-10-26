import TurnCard from "./TurnCard.jsx";

// Konuşmanın akışı (R7-15): her tur kendi soru balonu ve kartıyla bir satırdır; en alttaki soru
// kutusu App'te durur, burada yalnız turlar akar. Kartın kendisi TurnCard'da çözülür.
export default function Thread({ turns, onExpand, onReplay, onChoose, onChange, onSave }) {
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
            />
          </article>
        );
      })}
    </section>
  );
}
