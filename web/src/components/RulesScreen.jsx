import { useState } from "react";
import { useT } from "../i18n/index.js";
import * as api from "../lib/api.js";
import RuleForm from "./RuleForm.jsx";

// Kural ekranı (R5-16/R5-18): kümenin kuralları, indeksin tazeliği ve formun kendisi. Liste
// verisi üstten gelir; her kayıt, silme ve yeniden kurma sonrası üst aynı iki isteği yineler.
// Cümleler kataloğunda (R8-20); terimler, eş anlamlılar ve tablo adları veridir, çevrilmez.

function items(value) {
  return (Array.isArray(value) ? value : []).map((item) => String(item ?? "").trim()).filter(Boolean);
}

export default function RulesScreen({ rules = [], index = null, tables = [], loading = false, error = "", onRefresh, readOnly = false }) {
  const { t } = useT();
  const [draft, setDraft] = useState(null); // null: form kapalı | {} yeni kural | {rule}: düzenleme
  const [confirmId, setConfirmId] = useState(null);
  const [rebuilding, setRebuilding] = useState(false);
  const [note, setNote] = useState("");

  const rows = (Array.isArray(rules) ? rules : []).filter((rule) => rule?.id);
  const stale = Boolean(index) && index.fresh === false;

  const refresh = () => {
    setConfirmId(null);
    onRefresh?.();
  };

  const remove = async (id) => {
    try {
      await api.rulesRemove(id);
      setNote(t("rules.deleted", { id }));
      refresh();
    } catch (failure) {
      setNote(failure?.message || t("rules.deleteFailed"));
    }
  };

  const rebuild = async () => {
    setRebuilding(true);
    setNote("");
    try {
      await api.rebuild();
      setNote(t("rules.rebuilt"));
      refresh();
    } catch (failure) {
      setNote(failure?.message || t("rules.rebuildFailed"));
    } finally {
      setRebuilding(false);
    }
  };

  return (
    <section id="rules-screen" className="screen rules-screen">
      <div className="rules-head">
        <div>
          <h1 className="screen-title">{t("rules.title")}</h1>
          <p className="screen-lead">{t("rules.lead")}</p>
        </div>
        {!readOnly && (
          <button
            type="button"
            id="rule-add"
            className="btn btn-primary"
            onClick={() => {
              setNote("");
              setDraft({});
            }}
          >
            {t("rules.add")}
          </button>
        )}
      </div>

      {readOnly && (
        <p className="rules-readonly" id="rules-readonly-note">
          {t("rules.readonly")}
        </p>
      )}

      {stale && (
        <div id="index-stale" className="rules-banner" role="status">
          <p className="rules-banner-text">
            {t("rules.stale")}
            {index.reason ? ` ${index.reason}` : ""}
          </p>
          {!readOnly && (
            <button type="button" id="index-rebuild" className="btn" onClick={rebuild} disabled={rebuilding}>
              {rebuilding ? t("rules.rebuilding") : t("rules.rebuild")}
            </button>
          )}
        </div>
      )}

      {error && <p className="rules-note is-error">{error}</p>}
      {note && <p className="rules-note">{note}</p>}

      {!draft && (
        <div className="table-wrap">
          <table className="rules-table">
            <thead>
              <tr>
                <th scope="col">{t("rules.col.term")}</th>
                <th scope="col">{t("rules.col.synonyms")}</th>
                <th scope="col">{t("rules.col.tables")}</th>
                {!readOnly && (
                  <th scope="col" className="rules-col-actions">
                    {t("rules.col.actions")}
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr>
                  <td className="rules-empty" colSpan={readOnly ? 3 : 4}>
                    {loading ? t("rules.empty.loading") : readOnly ? t("rules.empty.none") : t("rules.empty.noneAdmin")}
                  </td>
                </tr>
              )}
              {rows.map((rule) => {
                const synonyms = items(rule.synonyms);
                const synonymsEn = items(rule.synonyms_en);
                return (
                  <tr key={rule.id}>
                    <th scope="row" className="rules-term">
                      <span className="rules-term-name">{String(rule.term ?? "").trim() || rule.id}</span>
                      <span className="rules-id">{rule.id}</span>
                    </th>
                    <td className="rules-list">
                      {synonyms.join(", ") || (synonymsEn.length ? "" : "—")}
                      {synonymsEn.length > 0 && (
                        <span className="rules-synonyms-en" lang="en">
                          <span className="rules-synonyms-en-tag">EN</span>
                          {synonymsEn.join(", ")}
                        </span>
                      )}
                    </td>
                    <td className="rules-list">{items(rule.tables).join(", ") || "—"}</td>
                    {!readOnly && (
                      <td className="rules-actions">
                        {confirmId === rule.id ? (
                          <span className="rules-confirm">
                            {t("rules.confirmDelete")}
                            <button type="button" className="btn btn-ghost" onClick={() => remove(rule.id)}>
                              {t("rules.confirmYes")}
                            </button>
                            <button type="button" className="btn btn-ghost" onClick={() => setConfirmId(null)}>
                              {t("rules.cancel")}
                            </button>
                          </span>
                        ) : (
                          <>
                            <button
                              type="button"
                              className="btn btn-ghost"
                              onClick={() => {
                                setNote("");
                                setDraft({ rule });
                              }}
                            >
                              {t("rules.edit")}
                            </button>
                            <button type="button" className="btn btn-ghost" onClick={() => setConfirmId(rule.id)}>
                              {t("rules.delete")}
                            </button>
                          </>
                        )}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {draft && (
        <RuleForm
          rule={draft.rule ?? null}
          tables={tables}
          onSaved={() => {
            setDraft(null);
            setNote(t("rules.saved"));
            refresh();
          }}
          onCancel={() => setDraft(null)}
        />
      )}
    </section>
  );
}
