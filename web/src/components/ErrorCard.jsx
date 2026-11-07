// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { useState } from "react";

// Hata kartının türleri (R5-18): payload'ın hatası hangi adla gelirse gelsin ekranda dört başlıktan
// birine iner; tanınmayan her tür "Cevap üretilemedi" + neden cümlesidir.
const CARDS = {
  llm_error: {
    title: "Model yanıt vermiyor",
    hint: "LLM sunucusunun açık olup olmadığına bakın; uç nokta NL2SQL_LLM_BASE_URL ile değiştirilir.",
  },
  index: {
    title: "İndeks eski",
    hint: "Şema ya da kurallar değişti. İndeksi yeniden kurduktan sonra soruyu yeniden sorun.",
  },
  network: {
    title: "Sunucuya ulaşılamadı",
    hint: "Bilgin sunucusu çalışmıyor; `python -m nl2sql serve` ile başlatın.",
  },
  failed: { title: "Cevap üretilemedi", hint: "" },
};

export function errorCardKind(kind) {
  return CARDS[kind] ? kind : "failed";
}

export default function ErrorCard({ kind, message, onRebuild }) {
  const type = errorCardKind(kind);
  const card = CARDS[type];
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
      setNote(error?.message || "İndeks yeniden kurulamadı.");
    }
  };

  const reason = message && message !== card.title ? message : "";

  return (
    <section id="error-card" className="card error-card" role="alert">
      <h2 className="error-title">{card.title}</h2>
      {card.hint && <p className="error-hint">{card.hint}</p>}
      {reason && <p className="error-reason">{reason}</p>}
      {type === "index" && (
        <div className="error-actions">
          <button type="button" id="error-rebuild" className="btn" onClick={rebuild} disabled={phase === "working"}>
            {phase === "working" ? "kuruluyor…" : phase === "done" ? "İndeks güncel." : "İndeksi yeniden kur"}
          </button>
          {phase === "done" && <span className="error-hint">Soruyu yeniden sorabilirsin.</span>}
        </div>
      )}
      {note && <p className="error-reason">{note}</p>}
    </section>
  );
}
