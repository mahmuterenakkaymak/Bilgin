import { useState } from "react";
import * as api from "../lib/api.js";
import RuleForm from "./RuleForm.jsx";

// Kural ekranı (R5-16/R5-18): kümenin kuralları, indeksin tazeliği ve formun kendisi. Liste
// verisi üstten gelir; her kayıt, silme ve yeniden kurma sonrası üst aynı iki isteği yineler.
const STALE_MESSAGE = "Kurallar değişti, indeks eski.";

function items(value) {
  return (Array.isArray(value) ? value : []).map((item) => String(item ?? "").trim()).filter(Boolean);
}

export default function RulesScreen({ rules = [], index = null, tables = [], loading = false, error = "", onRefresh, readOnly = false }) {
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
      setNote(`“${id}” silindi.`);
      refresh();
    } catch (failure) {
      setNote(failure?.message || "Kural silinemedi.");
    }
  };

  const rebuild = async () => {
    setRebuilding(true);
    setNote("");
    try {
      await api.rebuild();
      setNote("İndeks güncel.");
      refresh();
    } catch (failure) {
      setNote(failure?.message || "İndeks yeniden kurulamadı.");
    } finally {
      setRebuilding(false);
    }
  };

  return (
    <section id="rules-screen" className="screen rules-screen">
      <div className="rules-head">
        <div>
          <h1 className="screen-title">İş kuralları</h1>
          <p className="screen-lead">Kurallar, Bilgin'in bir soruda hangi terimi ne anladığını belirler.</p>
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
            Yeni kural
          </button>
        )}
      </div>

      {readOnly && (
        <p className="rules-readonly" id="rules-readonly-note">
          İş kurallarını yalnız yönetici değiştirebilir.
        </p>
      )}

      {stale && (
        <div id="index-stale" className="rules-banner" role="status">
          <p className="rules-banner-text">
            {STALE_MESSAGE}
            {index.reason ? ` ${index.reason}` : ""}
          </p>
          {!readOnly && (
            <button type="button" id="index-rebuild" className="btn" onClick={rebuild} disabled={rebuilding}>
              {rebuilding ? "kuruluyor…" : "İndeksi yeniden kur"}
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
                <th scope="col">Terim</th>
                <th scope="col">Eş anlamlılar</th>
                <th scope="col">Tablolar</th>
                {!readOnly && (
                  <th scope="col" className="rules-col-actions">
                    İşlem
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr>
                  <td className="rules-empty" colSpan={readOnly ? 3 : 4}>
                    {loading
                      ? "Kurallar okunuyor…"
                      : readOnly
                        ? "Henüz kural yok."
                        : "Henüz kural yok. “Yeni kural” ile ekleyin."}
                  </td>
                </tr>
              )}
              {rows.map((rule) => (
                <tr key={rule.id}>
                  <th scope="row" className="rules-term">
                    <span className="rules-term-name">{String(rule.term ?? "").trim() || rule.id}</span>
                    <span className="rules-id">{rule.id}</span>
                  </th>
                  <td className="rules-list">{items(rule.synonyms).join(", ") || "—"}</td>
                  <td className="rules-list">{items(rule.tables).join(", ") || "—"}</td>
                  {!readOnly && (
                    <td className="rules-actions">
                      {confirmId === rule.id ? (
                        <span className="rules-confirm">
                          Silinsin mi?
                          <button type="button" className="btn btn-ghost" onClick={() => remove(rule.id)}>
                            Evet
                          </button>
                          <button type="button" className="btn btn-ghost" onClick={() => setConfirmId(null)}>
                            Vazgeç
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
                            Düzenle
                          </button>
                          <button type="button" className="btn btn-ghost" onClick={() => setConfirmId(rule.id)}>
                            Sil
                          </button>
                        </>
                      )}
                    </td>
                  )}
                </tr>
              ))}
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
            setNote("Kural kaydedildi. İndeksi yeniden kurmayı unutmayın.");
            refresh();
          }}
          onCancel={() => setDraft(null)}
        />
      )}
    </section>
  );
}
