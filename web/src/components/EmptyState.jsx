// Hiç soru sorulmamış ekranın açılışı: iki cümle ve örnek çipler (R5-18).
// ASSUMPTION: boş durumdayken çipler burada, soru sorulduktan sonra AskBox'ın altında durur;
// aynı çip iki kez görünmesin diye kutu boş durumdayken kendi çip sırasını vermez.
export default function EmptyState({ examples = [], onSelect }) {
  return (
    <section className="card empty-state">
      <h1 className="screen-title">Verinize Türkçe soru sorun</h1>
      <p className="screen-lead">Bilgin SQL'i yazar, sonucu ve nasıl hesapladığını gösterir.</p>
      {examples.length > 0 && (
        <div className="examples">
          {examples.map((example, index) => (
            <button
              type="button"
              key={`${index}-${example?.question ?? ""}`}
              className="example-chip"
              title={example?.question ?? ""}
              onClick={() => onSelect(example?.question)}
            >
              {example?.question}
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
