import { useEffect, useState } from "react";
import * as api from "../lib/api.js";
import {
  AUTHS,
  AUTH_LABELS,
  DPAPI_MESSAGE,
  EMPTY_FORM,
  ENV_SOURCE_MESSAGE,
  clientErrors,
  toForm,
  toPayload,
} from "../lib/connForm.js";

// Veritabanı bağlantıları ekranı (R7-27): her SQL Server kümesinin kendi girişi burada doldurulur,
// yani küme değişirken veritabanı da yeniden başlatmadan değişir. Parola hiçbir cevapta
// dönmediği için alan hiç doldurulmaz — boş bırakılan parola sunucuda saklı olanı korur.
// "Bağlantıyı test et" ile "Kaydet" aynı yoklamadan geçer: yazabilen bir giriş reddedilir ve
// hiçbir satır yazılmaz, yönetici de hangi denetimin neden düştüğünü satır satır okur.

// Durum noktası arka plan yoklamasının cevabıdır (R7-25); istek hiçbir zaman onu beklemez.
const STATE_LABELS = { ok: "Bağlı", down: "Erişilemiyor", unknown: "Denenmedi", none: "Kurulu değil" };

function text(value) {
  return typeof value === "string" ? value.trim() : "";
}

function cell(value) {
  return text(value) || "—";
}

function dot(state) {
  const tone = STATE_LABELS[state] ? state : "unknown";
  return { tone, label: STATE_LABELS[tone] };
}

// "2026-10-27T09:15:00+00:00" → "27 Ekim 2026 12:15". ASSUMPTION: sunucu UTC yazıyor, dilim
// yalnız gösterim; okunamayan tarih "—" okunur, hücre boş kalmaz.
function stamp(value) {
  const date = new Date(typeof value === "string" ? value : Number.NaN);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("tr-TR", {
    day: "2-digit",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// Alanın üç hali tek yerde: etiket, girdi, altında ya ipucu ya reddin cümlesi.
function Field({ id, label, hint, error, value, type = "text", autoComplete = "off", placeholder, disabled, onChange }) {
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className="field-input"
        type={type}
        value={value}
        placeholder={placeholder}
        autoComplete={autoComplete}
        disabled={disabled}
        aria-invalid={error ? "true" : undefined}
        aria-describedby={`${id}-note`}
        onChange={onChange}
      />
      <p className={error ? "field-error" : "field-hint"} id={`${id}-note`}>
        {error || hint}
      </p>
    </div>
  );
}

export default function ConnectionsScreen({ connections = [], loading = false, error = "", onRefresh }) {
  const [row, setRow] = useState(null); // açılan satır: sözleşme "connection (public)"
  const [form, setForm] = useState(EMPTY_FORM);
  const [fieldErrors, setFieldErrors] = useState({});
  const [failure, setFailure] = useState("");
  const [note, setNote] = useState("");
  const [report, setReport] = useState(null); // sözleşme "guard report"
  const [busy, setBusy] = useState(""); // "" | "test" | "save"
  const [loadingName, setLoadingName] = useState(""); // satırı okunan küme
  const [secretOff, setSecretOff] = useState(false); // bu sunucu parolayı saklayamıyor

  const rows = (Array.isArray(connections) ? connections : []).filter((item) => text(item?.dataset));
  const dataset = text(row?.dataset);
  // Ortam değişkeninin kazandığı satıra ekrandan yazılmaz (R7-23); parolayı saklayamayan bir
  // sunucuda da formun yazacak bir şeyi kalmaz — cümleyi sunucu ilk denemede söyler.
  const readOnly = Boolean(row?.read_only_form) || secretOff;
  const pending = busy !== "" || loadingName !== "";
  const problem = error || failure;
  const emptyText = error
    ? "Bağlantılar okunamadı."
    : loading
      ? "Bağlantılar okunuyor…"
      : "SQL Server'a bağlı veri kümesi yok; yeni bir küme kurunca burada listelenir.";
  const lines = (Array.isArray(report?.lines) ? report.lines : []).filter((line) => text(line?.message));
  const missing = (Array.isArray(report?.missing_tables) ? report.missing_tables : [])
    .map((name) => text(name))
    .filter(Boolean);
  const script = text(report?.login_script_url);

  const change = (name) => (event) => {
    const value = event.target.type === "checkbox" ? event.target.checked : event.target.value;
    setForm((current) => ({ ...current, [name]: value }));
    setFieldErrors((current) => (current[name] ? { ...current, [name]: "" } : current));
  };

  // Satır sunucudan okunur: saklı sır var mı, ortam değişkeni kazanmış mı — form ancak o zaman
  // doğru davranır. Cevap parolayı taşımaz, o yüzden parola alanı boş kalır.
  const edit = (name) => {
    setLoadingName(name);
    setFailure("");
    setNote("");
    setReport(null);
    setFieldErrors({});
    api
      .connectionsGet(name)
      .then((payload) => {
        setRow(payload ?? null);
        setForm(toForm(payload));
        setSecretOff(false);
      })
      .catch((rejected) => setFailure(rejected?.message || "Bağlantı okunamadı."))
      .finally(() => setLoadingName(""));
  };

  const invalid = () => {
    const errors = clientErrors(form, { hasSecret: Boolean(row?.has_secret) });
    setFieldErrors(errors);
    return Object.keys(errors).length > 0;
  };

  const runTest = () => {
    if (!dataset || invalid()) return;
    setBusy("test");
    setFailure("");
    setReport(null);
    api
      .connectionsTest(dataset, toPayload(form))
      .then((payload) => setReport(payload ?? null))
      .catch((rejected) => setFailure(rejected?.message || "Bağlantı denenemedi."))
      .finally(() => setBusy(""));
  };

  const save = () => {
    if (!dataset || invalid()) return;
    setBusy("save");
    setFailure("");
    setReport(null);
    api
      .connectionsSave(dataset, toPayload(form))
      .then((payload) => {
        // Cevabın satırı formu da tazeler: ilk kayıtta `has_secret` true olur, sonraki
        // kaydetmede boş parola "koru" sayılır.
        if (payload?.connection) setRow(payload.connection);
        setForm((current) => ({ ...current, password: "" }));
        setReport(payload?.guard ?? null);
        setNote("Bağlantı kaydedildi.");
        onRefresh?.();
      })
      .catch((rejected) => {
        if (rejected?.message === DPAPI_MESSAGE) setSecretOff(true);
        setFailure(rejected?.message || "Bağlantı kaydedilemedi.");
      })
      .finally(() => setBusy(""));
  };

  return (
    <section id="conn-screen" className="screen conn-screen">
      <div>
        <h1 className="screen-title">Veritabanı bağlantıları</h1>
        <p className="screen-lead">
          Her SQL Server kümesinin kendi girişi; kaydedildiği an geçerlidir. Parola sunucuda
          şifreli durur ve ekrana hiç dönmez.
        </p>
      </div>

      <div className="table-wrap">
        <table className="conn-table">
          <thead>
            <tr>
              <th scope="col">Veri kümesi</th>
              <th scope="col">Durum</th>
              <th scope="col">Sunucu / veritabanı</th>
              <th scope="col">Son başarılı</th>
              <th scope="col">Son hata</th>
              <th scope="col" className="conn-col-actions">
                İşlemler
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td className="conn-empty" colSpan={6}>
                  {emptyText}
                </td>
              </tr>
            )}
            {rows.map((item) => {
              const name = text(item?.dataset);
              const status = dot(item?.state);
              const ok = stamp(item?.last_ok_at);
              const failureLine = text(item?.last_error);
              return (
                <tr key={name}>
                  <th scope="row" className="conn-name">
                    {name}
                    {item?.read_only_form && (
                      <span className="conn-env" title="Bağlantı ortam değişkeninden geliyor; ekrandan değiştirilemez.">
                        Ortam değişkeninden
                      </span>
                    )}
                  </th>
                  <td className="conn-status">
                    <span className={`db-dot db-dot-${status.tone}`} role="img" aria-label={status.label} />
                    {status.label}
                  </td>
                  <td className="conn-target">
                    <span className="conn-server">{cell(item?.server)}</span>
                    <span className="conn-database">{cell(item?.database)}</span>
                  </td>
                  <td className="conn-success">{ok || "—"}</td>
                  <td className="conn-failure" title={failureLine || undefined}>
                    {failureLine || "—"}
                  </td>
                  <td className="conn-actions">
                    <button
                      type="button"
                      className="btn btn-ghost"
                      data-conn-edit={name}
                      disabled={loadingName !== ""}
                      onClick={() => edit(name)}
                    >
                      {loadingName === name ? "Okunuyor…" : "Düzenle"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <form
        id="conn-form"
        className="card conn-form"
        onSubmit={(event) => {
          event.preventDefault();
          save();
        }}
      >
        <h2 className="rule-form-title">{dataset ? `Bağlantı · ${dataset}` : "Bağlantı"}</h2>
        {!dataset && (
          <p className="field-hint" id="conn-hint">
            Düzenlemek için yukarıdaki bir satırdan “Düzenle”yi seçin.
          </p>
        )}
        {row?.read_only_form && (
          <p className="conn-readonly" id="conn-readonly" role="status">
            {ENV_SOURCE_MESSAGE}
          </p>
        )}
        {problem && (
          <p className="conn-error" id="conn-error" role="alert">
            {problem}
          </p>
        )}
        {!problem && note && (
          <p className="conn-note" id="conn-note" role="status">
            {note}
          </p>
        )}
        <div className="conn-fields">
          <Field
            id="conn-server"
            label="Sunucu"
            hint="Sunucu adı ya da IP adresi; örnek: 10.0.0.5"
            error={fieldErrors.server}
            value={form.server}
            disabled={readOnly}
            onChange={change("server")}
          />
          <Field
            id="conn-database"
            label="Veritabanı"
            hint="Kümenin baktığı veritabanının adı."
            error={fieldErrors.database}
            value={form.database}
            disabled={readOnly}
            onChange={change("database")}
          />
          <div className="field">
            <label className="field-label" htmlFor="conn-auth">
              Kimlik doğrulama
            </label>
            <select
              id="conn-auth"
              className="field-input"
              value={form.auth}
              disabled={readOnly}
              aria-describedby="conn-auth-note"
              onChange={change("auth")}
            >
              {AUTHS.map((auth) => (
                <option value={auth} key={auth}>
                  {AUTH_LABELS[auth] ?? auth}
                </option>
              ))}
            </select>
            <p className="field-hint" id="conn-auth-note">
              Windows kimliği sunucu sürecinin kendi hesabıyla bağlanır.
            </p>
          </div>
          <Field
            id="conn-username"
            label="Kullanıcı adı"
            hint={
              form.auth === "windows"
                ? "Windows kimliğinde kullanıcı adı istenmez."
                : "Sunucudaki salt okunur girişin adı."
            }
            error={fieldErrors.username}
            value={form.username}
            disabled={readOnly || form.auth === "windows"}
            onChange={change("username")}
          />
          <Field
            id="conn-password"
            label="Parola"
            hint={row?.has_secret ? "Boş bırakılırsa saklı parola korunur." : "Sunucuda şifrelenerek saklanır."}
            error={fieldErrors.password}
            value={form.password}
            type="password"
            placeholder="değiştirmek için yazın"
            autoComplete="new-password"
            disabled={readOnly}
            onChange={change("password")}
          />
          <div className="conn-checks">
            <label className="conn-check" htmlFor="conn-encrypt">
              <input
                id="conn-encrypt"
                type="checkbox"
                checked={form.encrypt !== false}
                disabled={readOnly}
                onChange={change("encrypt")}
              />
              Bağlantıyı şifrele (Encrypt)
            </label>
            <label className="conn-check" htmlFor="conn-trust">
              <input
                id="conn-trust"
                type="checkbox"
                checked={form.trust !== false}
                disabled={readOnly}
                onChange={change("trust")}
              />
              Sunucu sertifikasına güven (TrustServerCertificate)
            </label>
          </div>
        </div>
        <div className="conn-buttons">
          <button type="button" id="conn-test" className="btn" onClick={runTest} disabled={readOnly || pending || !dataset}>
            {busy === "test" ? "Deneniyor…" : "Bağlantıyı test et"}
          </button>
          <button type="submit" id="conn-save" className="btn btn-primary" disabled={readOnly || pending || !dataset}>
            {busy === "save" ? "Kaydediliyor…" : "Kaydet"}
          </button>
        </div>
        {report && (
          <div className="conn-result" id="conn-result" role="status">
            <p className={report.ok ? "conn-result-head is-ok" : "conn-result-head is-err"}>
              {report.ok ? "Bu giriş salt okunur: kaydedilebilir." : "Bu giriş kaydedilemez — aşağıdaki denetimler düştü."}
            </p>
            <ul className="conn-lines">
              {lines.map((line, index) => (
                <li className={line.ok ? "is-ok" : "is-err"} key={`${text(line?.check)}-${index}`}>
                  <span aria-hidden="true">{line.ok ? "✓" : "✗"}</span>
                  <span>{text(line?.message)}</span>
                </li>
              ))}
            </ul>
            {missing.length > 0 && (
              <p className="conn-missing" id="conn-missing">
                Bu girişle okunamayan tablolar: {missing.join(", ")}.
              </p>
            )}
            {script && (
              <a className="conn-script" id="conn-login-script" href={script} download>
                Salt okunur giriş betiğini indir
              </a>
            )}
          </div>
        )}
      </form>
    </section>
  );
}

// Ekranın akışı: liste tek istekten okunur ve her kayıt sonrası aynı istek yinelenir ki tablo
// sunucudaki halini — yoklamanın yeni noktasıyla birlikte — göstersin.
export function ConnectionsFlow() {
  const [rows, setRows] = useState(null); // null: henüz okunmadı
  const [error, setError] = useState("");

  const refresh = () => {
    api
      .connectionsList()
      .then((payload) => setRows(Array.isArray(payload?.connections) ? payload.connections : []))
      .catch((failure) => setError(failure?.message || "Bağlantılar okunamadı."));
  };

  useEffect(refresh, []);

  return <ConnectionsScreen connections={rows ?? []} loading={!rows} error={error} onRefresh={refresh} />;
}
