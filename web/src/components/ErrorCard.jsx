import { useState } from "react";
import { useT } from "../i18n/index.js";

// Hata kartının türleri (R5-18): payload'ın hatası hangi adla gelirse gelsin ekranda dört başlıktan
// birine iner; tanınmayan her tür genel başlık + neden cümlesidir. Başlık ve ipucu katalogdan (R8-18);
// neden cümlesi sunucunun kendi cümlesidir, çevrilmeden okunur.
const CARDS = {
  llm_error: { title: "error.llm.title", hint: "error.llm.hint" },
  index: { title: "error.index.title", hint: "error.index.hint" },
  network: { title: "error.network.title", hint: "error.network.hint" },
  failed: { title: "error.failed.title", hint: "" },
};

export function errorCardKind(kind) {
  return CARDS[kind] ? kind : "failed";
}

export default function ErrorCard({ kind, message, onRebuild }) {
  const { t } = useT();
  const type = errorCardKind(kind);
  const card = CARDS[type];
  const title = t(card.title);
  const [phase, setPhase] = useState("idle"); // idle | working | done
  const [note, setNote] = useState("");

  const rebuild = async () => {
    setPhase("working");
    setNote("");
    try {
      await onRebuild();
      setPhase("done");
    } catch (error) {
      setPhase("idle");
      setNote(error?.message || t("error.rebuildFailed"));
    }
  };

  // Reddin cümlesi başlıkla aynıysa bir daha yazılmaz: kart onu zaten başlıkta söylüyor.
  const reason = message && message !== title ? message : "";

  return (
    <section id="error-card" className="card error-card" role="alert">
      <h2 className="error-title">{title}</h2>
      {card.hint && <p className="error-hint">{t(card.hint)}</p>}
      {reason && <p className="error-reason">{reason}</p>}
      {type === "index" && (
        <div className="error-actions">
          <button type="button" id="error-rebuild" className="btn" onClick={rebuild} disabled={phase === "working"}>
            {phase === "working" ? t("error.rebuilding") : phase === "done" ? t("error.rebuilt") : t("error.rebuild")}
          </button>
          {phase === "done" && <span className="error-hint">{t("error.askAgain")}</span>}
        </div>
      )}
      {note && <p className="error-reason">{note}</p>}
    </section>
  );
}
