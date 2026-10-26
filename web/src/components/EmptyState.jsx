// Hiç soru sorulmamış ekranın açılışı: iki cümle ve örnek çipler (R5-18).
// ASSUMPTION: boş durumdayken çipler burada, soru sorulduktan sonra AskBox'ın altında durur;
// aynı çip iki kez görünmesin diye kutu boş durumdayken kendi çip sırasını vermez.
// Çip yoksa kutu başlık ve tek cümlenin altında boş bir alanla kalmasın: durum söylenir ve
// yönetici, kümenin açığını kapattığı tek ekrana, İş kuralları'na bağlanır (`rulesHint`).
// ASSUMPTION: ad geldiğinde lead'in kendisi onun cümlesidir; iki cümle üst üste binmesin (M22: tek
// cümle, yeni veri yok). Ad yoksa — sağlık çıktısı henüz gelmediyse — ekran bugünkü cümlesiyle açılır.
export default function EmptyState({ examples = [], rulesHint = false, datasetName = "", onSelect }) {
  return (
    <section className="card empty-state">
      <h1 className="screen-title">Verinize Türkçe soru sorun</h1>
      <p className="screen-lead">
        {datasetName
          ? `«${datasetName}» üzerinde soruyorsun; örnekler onun tablolarından.`
          : "Bilgin SQL'i yazar, sonucu ve nasıl hesapladığını gösterir."}
      </p>
      {examples.length > 0 ? (
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
      ) : (
        <p className="empty-hint" id="empty-hint">
          Bu veri kümesinde henüz örnek soru yok — sorunu yukarıya yaz, Bilgin ilk kez gördüğü bir
          soruyu da SQL'e çevirir.
          {rulesHint && (
            <>
              {" Kümenin iş kuralı da yok: iş terimlerini hesaba katması için "}
              <a href="#/kurallar">İş kuralları</a>
              {" ekranından ilk kuralını ekle."}
            </>
          )}
        </p>
      )}
    </section>
  );
}
