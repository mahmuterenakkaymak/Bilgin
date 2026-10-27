import { useState } from "react";
import { useT } from "../i18n/index.js";
import * as api from "../lib/api.js";
import { BUSINESS_ROLE_CODES, EVERY_ROLE, roleLabel, suggestDisplay } from "../lib/startCards.js";

// Hazır soru formu (PLAN R7-21): yönetici cevaplanmış bir soruyu panonun kartı yapar. Gövde
// sözleşme "ready create body"dir: `sql` yoktur — sunucu onu `audit_id`nin kaydından alır ve
// onayda bir daha koşturur. Yürümeyen sorgunun 422'si yürütücünün kendi cümlesidir, burada
// uydurulmuş bir yazıya dönüşmez.
const DISPLAYS = [
  ["number", "ready.display.number"],
  ["chart", "ready.display.chart"],
  ["table", "ready.display.table"],
];

// "*" başta: kartın varsayılanı her rolün panosudur. Rol adları lib/startCards.js'in `roleLabel`ı
// ile kataloğun anahtarlarından okunur, yani ekran ile defter aynı beş rolü söyler.
const ROLES = [EVERY_ROLE, ...BUSINESS_ROLE_CODES];

export default function ReadyQuestionForm({ payload, onCancel }) {
  const { lang, t } = useT();
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
      setSaved(t("ready.form.saved", { role: roleLabel(form.business_role, lang) }));
    } catch (failure) {
      setError(failure?.message || t("ready.form.failed"));
    } finally {
      setSaving(false);
    }
  };

  const suggestedKey = DISPLAYS.find(([kind]) => kind === suggested)?.[1] ?? "";

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
        <h2 className="rule-form-title">{t("answer.makeReady")}</h2>
        {saved ? (
          <p className="ready-saved" id="ready-saved" role="status">
            {saved}
          </p>
        ) : (
          <p className="rule-form-sub">{t("ready.form.sub")}</p>
        )}
      </div>

      {error && <p className="rule-errors" id="ready-error" role="alert">{error}</p>}

      {!saved && (
        <div className="rule-fields">
          <div className="field">
            <label className="field-label" htmlFor="ready-title">{t("ready.field.title")}</label>
            <input
              id="ready-title"
              className="field-input"
              type="text"
              value={form.title}
              onChange={change("title")}
            />
            <p className="field-hint">{t("ready.hint.title")}</p>
          </div>

          <div className="field">
            <label className="field-label" htmlFor="ready-role">{t("ready.field.role")}</label>
            <select
              id="ready-role"
              className="field-input"
              value={form.business_role}
              onChange={change("business_role")}
            >
              {ROLES.map((role) => (
                <option key={role} value={role}>
                  {roleLabel(role, lang)}
                </option>
              ))}
            </select>
            <p className="field-hint">{t("ready.form.hint.role")}</p>
          </div>

          <div className="field">
            <label className="field-label" htmlFor="ready-display">{t("ready.field.display")}</label>
            <select
              id="ready-display"
              className="field-input"
              value={form.display}
              onChange={change("display")}
            >
              {DISPLAYS.map(([kind, key]) => (
                <option key={kind} value={kind}>
                  {t(key)}
                </option>
              ))}
            </select>
            <p className="field-hint">{t("ready.form.hint.display", { label: suggestedKey ? t(suggestedKey) : "" })}</p>
          </div>

          <div className="field field-wide">
            <label className="field-label" htmlFor="ready-question">{t("ready.field.question")}</label>
            <textarea
              id="ready-question"
              className="field-input"
              rows={2}
              value={form.question}
              onChange={change("question")}
            />
            <p className="field-hint">{t("ready.form.hint.question")}</p>
          </div>
        </div>
      )}

      <div className="rule-form-actions">
        {saved ? (
          <button type="button" id="ready-cancel" className="btn" onClick={() => onCancel?.()}>
            {t("ready.form.close")}
          </button>
        ) : (
          <>
            <button type="submit" id="ready-save" className="btn btn-primary" disabled={saving}>
              {saving ? t("ready.form.saving") : t("ready.save")}
            </button>
            <button
              type="button"
              id="ready-cancel"
              className="btn"
              onClick={() => onCancel?.()}
              disabled={saving}
            >
              {t("ready.cancel")}
            </button>
          </>
        )}
      </div>
    </form>
  );
}
