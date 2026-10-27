// Soru kutusu: Enter gönderir, Shift+Enter alt satıra iner; boş metin ve koşan bir soru
// düğmeyi kilitler (R5-18). Çipler kutunun altında durur, böylece cevaptan sonra da erişilir.
// Kutunun kendi cümleleri katalogdan (R8-18); örnek çiplerin sorusu verinin cümlesidir, çevrilmez.
import { useT } from "../i18n/index.js";

export default function AskBox({ value, onChange, onAsk, loading = false, examples = [] }) {
  const { t } = useT();
  const text = typeof value === "string" ? value : "";
  const blank = !text.trim();

  const send = () => {
    if (!blank && !loading) onAsk(text);
  };

  return (
    <form
      className="ask-box"
      onSubmit={(event) => {
        event.preventDefault();
        send();
      }}
    >
      <textarea
        id="question"
        className="question"
        aria-label={t("ask.label")}
        placeholder={t("ask.placeholder")}
        rows={2}
        value={text}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            send();
          }
        }}
      />
      <div className="ask-actions">
        <button type="submit" id="ask-button" className="btn btn-primary" disabled={loading || blank}>
          {loading ? t("ask.answer") : t("ask.submit")}
        </button>
        <span className="ask-hint">{t("ask.hint")}</span>
      </div>
      {examples.length > 0 && (
        <div className="examples">
          {examples.map((example, index) => (
            <button
              type="button"
              key={`${index}-${example?.question ?? ""}`}
              className="example-chip"
              disabled={loading}
              title={example?.question ?? ""}
              onClick={() => onAsk(example?.question)}
            >
              {example?.question}
            </button>
          ))}
        </div>
      )}
    </form>
  );
}
