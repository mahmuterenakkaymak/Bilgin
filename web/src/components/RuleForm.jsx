import { useState } from "react";
import * as api from "../lib/api.js";
import { clientErrors, fromForm, mergeErrors, toForm } from "../lib/rulesForm.js";

// Kural formu (R5-18): yeni kural ve düzenleme aynı kurulum. Düzenlemede kimlik sabittir —
// sunucu kuralı kimliğiyle bulur, değiştirmek yeni bir kural demek olurdu. Alan hatalıysa yazısı
// altına düşer, hepsi üstte #rule-errors altında da toplanır.
const FIELDS = [
  { name: "id", label: "Kimlik", hint: "Küçük harf, rakam, alt çizgi. Sonradan değişmez.", locked: true },
  { name: "term", label: "Terim", hint: "Soruda geçen ad, ör. “Net satış (iadeler düşülmüş)”." },
  { name: "synonyms", label: "Eş anlamlılar", hint: "Virgülle ayırın: net ciro, satış geliri." },
  { name: "tables", label: "Tablolar", hint: "Virgülle ayırın; adlar şemadan tamamlanır." },
  { name: "definition", label: "Tanım", kind: "textarea", hint: "Terimin iş tanımını buraya yazın." },
  { name: "sql_hint", label: "SQL ipucu", kind: "textarea", mono: true, hint: "Modelin tutunacağı ifade; zorunlu değil." },
  { name: "markers", label: "İşaretçiler", kind: "textarea", mono: true, rows: 3, hint: "Satır başına bir düzenli ifade." },
];

export default function RuleForm({ rule = null, tables = [], errors = [], onSaved, onCancel }) {
  const editing = Boolean(rule?.id);
  const [form, setForm] = useState(() => toForm(rule));
  const [serverErrors, setServerErrors] = useState(() => mergeErrors(errors));
  const [saving, setSaving] = useState(false);

  const messages = Object.values(serverErrors).filter(Boolean);

  const change = (name) => (event) => {
    setForm((current) => ({ ...current, [name]: event.target.value }));
    setServerErrors((current) => (current[name] ? { ...current, [name]: "" } : current));
  };

  const save = async () => {
    const invalid = clientErrors(form);
    if (Object.keys(invalid).length) {
      setServerErrors(invalid);
      return;
    }
    setSaving(true);
    try {
      const body = fromForm(form);
      const data = editing ? await api.rulesUpdate(rule.id, body) : await api.rulesCreate(body);
      onSaved?.(data);
    } catch (error) {
      const fields = mergeErrors(error?.errors);
      setServerErrors(Object.keys(fields).length ? fields : { "": error?.message || "Kural kaydedilemedi." });
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
        <h2 className="rule-form-title">{editing ? "Kuralı düzenle" : "Yeni kural"}</h2>
        {editing && <p className="rule-form-sub">Kaydedince indeks bayatlar; yeniden kurunca işler.</p>}
      </div>

      {messages.length > 0 && (
        <div id="rule-errors" className="rule-errors" role="alert">
          <p className="rule-errors-title">Kaydedilemedi — şunları düzeltin:</p>
          <ul className="rule-errors-list">
            {messages.map((message, index) => (
              <li key={`${index}-${message}`}>{message}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="rule-fields">
        {FIELDS.map((field) => (
          <div className={field.kind === "textarea" ? "field field-wide" : "field"} key={field.name}>
            <label className="field-label" htmlFor={`rule-${field.name}`}>
              {field.label}
            </label>
            {field.kind === "textarea" ? (
              <textarea
                id={`rule-${field.name}`}
                className={field.mono ? "field-input is-mono" : "field-input"}
                rows={field.rows ?? 4}
                value={form[field.name]}
                aria-invalid={serverErrors[field.name] ? "true" : undefined}
                aria-describedby={serverErrors[field.name] ? `rule-${field.name}-error` : undefined}
                onChange={change(field.name)}
              />
            ) : (
              <input
                id={`rule-${field.name}`}
                className="field-input"
                type="text"
                value={form[field.name]}
                disabled={field.locked && editing}
                list={field.name === "tables" ? "table-options" : undefined}
                aria-invalid={serverErrors[field.name] ? "true" : undefined}
                aria-describedby={serverErrors[field.name] ? `rule-${field.name}-error` : undefined}
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
              <p className="field-error" id={`rule-${field.name}-error`}>
                {serverErrors[field.name]}
              </p>
            ) : (
              <p className="field-hint">{field.hint}</p>
            )}
          </div>
        ))}
      </div>

      <div className="rule-form-actions">
        <button type="submit" id="rule-save" className="btn btn-primary" disabled={saving}>
          {saving ? "Kaydediliyor…" : "Kaydet"}
        </button>
        <button type="button" id="rule-cancel" className="btn" onClick={() => onCancel?.()} disabled={saving}>
          Vazgeç
        </button>
      </div>
    </form>
  );
}
