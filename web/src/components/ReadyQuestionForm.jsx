import { useState } from "react";
import * as api from "../lib/api.js";
import { BUSINESS_ROLES, EVERY_ROLE, EVERY_ROLE_LABEL, roleLabel, suggestDisplay } from "../lib/startCards.js";

// Hazır soru formu (PLAN R7-21): yönetici cevaplanmış bir soruyu panonun kartı yapar. Gövde
// sözleşme "ready create body"dir: `sql` yoktur — sunucu onu `audit_id`nin kaydından alır ve
// onayda bir daha koşturur. Yürümeyen sorgunun 422'si yürütücünün kendi cümlesidir, burada
// uydurulmuş bir yazıya dönüşmez.
const DISPLAYS = [
  ["number", "Tek sayı"],
  ["chart", "Grafik"],
  ["table", "Tablo"],
];

// "*" başta: kartın varsayılanı her rolün panosudur. Rol adları lib/startCards.js'in kendi
// listesinden gelir, yani ekran ile defter aynı beş rolü söyler.
const ROLES = [[EVERY_ROLE, EVERY_ROLE_LABEL], ...BUSINESS_ROLES.map((item) => [item.role, item.label])];

export default function ReadyQuestionForm({ payload, onCancel }) {
  const question = typeof payload?.question === "string" ? payload.question : "";
  const suggested = suggestDisplay(payload);
  const [form, setForm] = useState({
    title: question,
    question,
    display: suggested,
    business_role: EVERY_ROLE,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");

  const change = (name) => (event) => setForm((current) => ({ ...current, [name]: event.target.value }));

  const save = async () => {
    setSaving(true);
    setError("");
    try {
      await api.readyCreate({ ...form, audit_id: payload?.audit_id ?? "" });
      setSaved(`Hazır soru eklendi: ${roleLabel(form.business_role)} için panoda.`);
    } catch (failure) {
      setError(failure?.message || "Hazır soru kaydedilemedi.");
    } finally {
      setSaving(false);
    }
  };

  const suggestedLabel = DISPLAYS.find(([kind]) => kind === suggested)?.[1] ?? "";

  return (
    <form
      id="ready-form"
      className="card rule-form ready-form"
      onSubmit={(event) => {
        event.preventDefault();
        save();
      }}
    >
      <div className="rule-form-head">
        <h2 className="rule-form-title">Hazır soru yap</h2>
        {saved ? (
          <p className="ready-saved" id="ready-saved" role="status">
            {saved}
          </p>
        ) : (
          <p className="rule-form-sub">Kart bu sorunun kayıtlı SQL'iyle koşar; SQL gönderilmez.</p>
        )}
      </div>

      {error && <p className="rule-errors" id="ready-error" role="alert">{error}</p>}

      {!saved && (
        <div className="rule-fields">
          <div className="field">
            <label className="field-label" htmlFor="ready-title">Başlık</label>
            <input
              id="ready-title"
              className="field-input"
              type="text"
              value={form.title}
              onChange={change("title")}
            />
            <p className="field-hint">Panodaki kartın üstünde okunur.</p>
          </div>

          <div className="field">
            <label className="field-label" htmlFor="ready-role">İş rolü</label>
            <select
              id="ready-role"
              className="field-input"
              value={form.business_role}
              onChange={change("business_role")}
            >
              {ROLES.map(([role, label]) => (
                <option key={role} value={role}>
                  {label}
                </option>
              ))}
            </select>
            <p className="field-hint">Herkes kartı her rolün panosunda açılır.</p>
          </div>

          <div className="field">
            <label className="field-label" htmlFor="ready-display">Görünüm</label>
            <select
              id="ready-display"
              className="field-input"
              value={form.display}
              onChange={change("display")}
            >
              {DISPLAYS.map(([kind, label]) => (
                <option key={kind} value={kind}>
                  {label}
                </option>
              ))}
            </select>
            <p className="field-hint">Sonucun biçiminden önerilen: {suggestedLabel}.</p>
          </div>

          <div className="field field-wide">
            <label className="field-label" htmlFor="ready-question">Soru</label>
            <textarea
              id="ready-question"
              className="field-input"
              rows={2}
              value={form.question}
              onChange={change("question")}
            />
            <p className="field-hint">Karta tıklanınca bu cümle sorulur.</p>
          </div>
        </div>
      )}

      <div className="rule-form-actions">
        {saved ? (
          <button type="button" id="ready-cancel" className="btn" onClick={() => onCancel?.()}>
            Kapat
          </button>
        ) : (
          <>
            <button type="submit" id="ready-save" className="btn btn-primary" disabled={saving}>
              {saving ? "Kaydediliyor…" : "Kaydet"}
            </button>
            <button
              type="button"
              id="ready-cancel"
              className="btn"
              onClick={() => onCancel?.()}
              disabled={saving}
            >
              Vazgeç
            </button>
          </>
        )}
      </div>
    </form>
  );
}
