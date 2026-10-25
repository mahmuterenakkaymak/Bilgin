// Model iki okunuşu ayıramayınca sorar (R5-10): seçeneklerden biri sorunun üstüne eklenir ve
// soru yeniden koşulur (R5-11). Kart cevap değildir, o yüzden soruyu değiştirme yolu açık kalır.
export default function ClarificationCard({ payload, onChoose, onChange }) {
  const request = payload?.clarification ?? {};
  const question = typeof request.question === "string" ? request.question : "";
  const options = (Array.isArray(request.options) ? request.options : []).filter(
    (option) => typeof option === "string" && option.trim(),
  );

  return (
    <section id="clarification-card" className="card clarification-card">
      <h2 className="clarification-title">Netleştirelim</h2>
      {question && <p className="clarification-question">{question}</p>}
      {options.length > 0 && (
        <div className="clarification-options">
          {options.map((option, index) => (
            <button
              type="button"
              key={`${index}-${option}`}
              className="btn clarification-option"
              data-option-index={index}
              onClick={() => onChoose(option)}
            >
              {option}
            </button>
          ))}
        </div>
      )}
      <div className="clarification-actions">
        <button type="button" id="clarification-change" className="btn btn-ghost" onClick={onChange}>
          Soruyu değiştir
        </button>
      </div>
    </section>
  );
}
