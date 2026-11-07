// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { useEffect, useRef, useState } from "react";
import { useT } from "../i18n/index.js";
import * as api from "../lib/api.js";
import { clientErrors, fromForm, mergeErrors, toForm } from "../lib/rulesForm.js";

// Kural formu (R5-18): yeni kural ve düzenleme aynı kurulum. Düzenlemede kimlik sabittir —
// sunucu kuralı kimliğiyle bulur, değiştirmek yeni bir kural demek olurdu. Alan hatalıysa yazısı
// altına düşer, hepsi üstte #rule-errors altında da toplanır. Cümleler kataloğunda (R8-20);
// sunucunun reddi (422) kendi diliyle geldiği için olduğu gibi gösterilir.
const FIELDS = [
  { name: "id", labelKey: "rules.field.id", hintKey: "rules.hint.id", locked: true },
  { name: "term", labelKey: "rules.field.term", hintKey: "rules.hint.term" },
  { name: "synonyms", labelKey: "rules.field.synonyms", hintKey: "rules.hint.synonyms" },
  // ASSUMPTION: alanın adı API'nin alanı (`synonyms_en`), girdinin id'si R8-20'nin adı; alt çizgi
  // korunsaydı `#rule-synonyms_en` diğer girdilerin okunuşundan ayrılırdı.
  { name: "synonyms_en", id: "rule-synonyms-en", labelKey: "rules.field.synonymsEn", hintKey: "rules.hint.synonymsEn" },
  { name: "tables", labelKey: "rules.field.tables", hintKey: "rules.hint.tables" },
  { name: "definition", labelKey: "rules.field.definition", kind: "textarea", hintKey: "rules.hint.definition" },
  {
    name: "sql_hint",
    labelKey: "rules.field.sqlHint",
    kind: "textarea",
    mono: true,
    hintKey: "rules.hint.sqlHint",
  },
  {
    name: "markers",
    labelKey: "rules.field.markers",
    kind: "textarea",
    mono: true,
    rows: 3,
    hintKey: "rules.hint.markers",
  },
];

export default function RuleForm({ rule = null, tables = [], errors = [], onSaved, onCancel }) {
  const { t, lang } = useT();
  const editing = Boolean(rule?.id);
  // `synonyms_en` alanı olmayan kayıt forma boş metinle girer: girdi kontrollü, undefined görmez.
  const [form, setForm] = useState(() => ({ synonyms_en: "", ...toForm(rule) }));
  const [serverErrors, setServerErrors] = useState(() => mergeErrors(errors));
  const [saving, setSaving] = useState(false);
  const [rejected, setRejected] = useState(0); // her ret, özeti bir kez daha ekrana taşır
  const summary = useRef(null);

  const messages = Object.values(serverErrors).filter(Boolean);
  // ASSUMPTION: sayı yalnız alan hatalarını sayar — alansız mesajda sayılacak bir alan yoktur.
  const fieldCount = Object.keys(serverErrors).filter((key) => key && serverErrors[key]).length;

  // Özet formun başında, Kaydet ~1400 px aşağıda: reddedilen dokunuşun görülmesi için özet
  // odağa alınıp üstüne kayılır. Yalnız gönderim sonrası çalışır ki açılışta odak çalınmasın.
  useEffect(() => {
    if (!rejected) return;
    const node = summary.current;
    if (!node) return;
    node.focus();
    node.scrollIntoView?.({ block: "start", behavior: "smooth" });
  }, [rejected]);

  const change = (name) => (event) => {
    setForm((current) => ({ ...current, [name]: event.target.value }));
    setServerErrors((current) => (current[name] ? { ...current, [name]: "" } : current));
  };

  const save = async () => {
    const invalid = clientErrors(form, lang);
    if (Object.keys(invalid).length) {
      setServerErrors(invalid);
      setRejected((current) => current + 1);
      return;
    }
    setSaving(true);
    try {
      const body = fromForm(form);
      const data = editing ? await api.rulesUpdate(rule.id, body) : await api.rulesCreate(body);
      onSaved?.(data);
    } catch (error) {
      const fields = mergeErrors(error?.errors);
      setServerErrors(Object.keys(fields).length ? fields : { "": error?.message || t("rules.form.failed") });
      setRejected((current) => current + 1);
    } finally {
      setSaving(false);
    }
  };

  return (
    <form
      id="rule-form"
      className="card rule-form"
      onSubmit={(event) => {
        event.preventDefault();
        save();
      }}
    >
      <div className="rule-form-head">
        <h2 className="rule-form-title">{editing ? t("rules.form.titleEdit") : t("rules.form.titleNew")}</h2>
        {editing && <p className="rule-form-sub">{t("rules.form.sub")}</p>}
      </div>

      {messages.length > 0 && (
        <div id="rule-errors" className="rule-errors" role="alert" ref={summary} tabIndex={-1}>
          <p className="rule-errors-title">{t("rules.form.errorsTitle")}</p>
          <ul className="rule-errors-list">
            {messages.map((message, index) => (
              <li key={`${index}-${message}`}>{message}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="rule-fields">
        {FIELDS.map((field) => {
          const id = field.id ?? `rule-${field.name}`;
          const errorId = serverErrors[field.name] ? `${id}-error` : undefined;
          return (
            <div className={field.kind === "textarea" ? "field field-wide" : "field"} key={field.name}>
              <label className="field-label" htmlFor={id}>
                {t(field.labelKey)}
              </label>
              {field.kind === "textarea" ? (
                <textarea
                  id={id}
                  className={field.mono ? "field-input is-mono" : "field-input"}
                  rows={field.rows ?? 4}
                  value={form[field.name]}
                  aria-invalid={errorId ? "true" : undefined}
                  aria-describedby={errorId}
                  onChange={change(field.name)}
                />
              ) : (
                <input
                  id={id}
                  className="field-input"
                  type="text"
                  value={form[field.name]}
                  disabled={field.locked && editing}
                  list={field.name === "tables" ? "table-options" : undefined}
                  aria-invalid={errorId ? "true" : undefined}
                  aria-describedby={errorId}
                  onChange={change(field.name)}
                />
              )}
              {field.name === "tables" && (
                <datalist id="table-options">
                  {(Array.isArray(tables) ? tables : []).map((name) => (
                    <option value={String(name)} key={String(name)} />
                  ))}
                </datalist>
              )}
              {serverErrors[field.name] ? (
                <p className="field-error" id={errorId}>
                  {serverErrors[field.name]}
                </p>
              ) : (
                <p className="field-hint">{t(field.hintKey)}</p>
              )}
            </div>
          );
        })}
      </div>

      <div className="rule-form-actions">
        <button type="submit" id="rule-save" className="btn btn-primary" disabled={saving}>
          {saving ? t("rules.form.saving") : t("rules.form.save")}
        </button>
        <button type="button" id="rule-cancel" className="btn" onClick={() => onCancel?.()} disabled={saving}>
          {t("rules.cancel")}
        </button>
        {fieldCount > 0 && (
          <p className="rule-form-count" id="rule-error-count">
            {t(fieldCount === 1 ? "rules.form.count.one" : "rules.form.count", { count: fieldCount })}
          </p>
        )}
      </div>
    </form>
  );
}
