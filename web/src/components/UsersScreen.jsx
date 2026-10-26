import { useState } from "react";
import * as api from "../lib/api.js";
import { ROLE_LABELS } from "../lib/auth.js";
import { PASSWORD_MESSAGE, PASSWORD_MIN_LEN, ROLES, clientErrors, toPayload } from "../lib/usersForm.js";

// Kullanıcı ekranı (R6-19): yöneticinin defteri. Liste üstten okunur; her ekme ve güncelleme
// sonrası aynı istek yinelenir ki tablo sunucudaki halini göstersin. Reddin cümlesi değiştirilmeden
// #users-error'a düşer — son etkin yöneticiyi koruyan 409'un sözü de sunucunundur.
const EMPTY_FORM = { username: "", password: "", password2: "", role: "user" };

// Kendi rolü tek tıkla düşmez: değişince yönetici ekranları kapanır, o yüzden önce söz istenir.
const SELF_ROLE_QUESTION = "Kendi rolünüzü değiştiriyorsunuz; yönetici ekranları kapanır. Değiştirilsin mi?";

// ASSUMPTION: "Son giriş" tarayıcının yerel saatiyle okunur; sunucu UTC yazıyor, dilim yalnız gösterim.
function lastLogin(value) {
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
// `invalid` cümlesi olmayan hal: sunucunun reddi formun bandında duruyor, alan aynı cümleyi
// bir daha altta saymıyor — yalnız kendi hatasının işaretini taşıyor.
function Field({ id, label, hint, error, invalid = false, value, type = "text", autoComplete, onChange }) {
  const marked = Boolean(error) || invalid;
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>
        {label}
      </label>
      <input
        id={id}
        className="field-input"
        type={type}
        autoComplete={autoComplete}
        value={value}
        aria-invalid={marked ? "true" : undefined}
        aria-describedby={invalid ? `${id}-note users-error` : `${id}-note`}
        onChange={onChange}
      />
      <p className={error ? "field-error" : "field-hint"} id={`${id}-note`}>
        {error || hint}
      </p>
    </div>
  );
}

// Formun kendi cevabı: çıplak paragraf değil, bandı var — yoksa .screen-lead ile aynı renk ve
// boyutta kaldığı için sayfanın sözü sanılıyor (M19 review 2).
export function UsersNote({ children }) {
  return (
    <p className="users-note users-band" role="status">
      {children}
    </p>
  );
}

export default function UsersScreen({ users = [], currentUser = null, loading = false, error = "", onRefresh }) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [fieldErrors, setFieldErrors] = useState({});
  const [flagged, setFlagged] = useState(""); // sunucunun reddettiği alan: cümle bantta, işaret alanda
  const [adding, setAdding] = useState(false);
  const [busyId, setBusyId] = useState(null); // kendi isteği süren satır
  const [failure, setFailure] = useState("");
  const [note, setNote] = useState("");
  const [resetId, setResetId] = useState(null);
  const [resetValue, setResetValue] = useState("");
  const [resetError, setResetError] = useState("");

  const rows = (Array.isArray(users) ? users : []).filter((user) => user?.id !== undefined && user?.id !== null);
  // ASSUMPTION: /api/auth/me yalnız {username, role} döndürüyor (id yok), o yüzden kendi satırı
  // addan çözülür; sunucu adları küçük harfe çeviriyor, karşılaştırma da küçük harfle yapılıyor.
  const selfName = String(currentUser?.username ?? "").toLowerCase();
  const problem = error || failure;
  // Okuma düşerse tablo "okunuyor…"da beklememeli: yukarıdaki cümle ne olduğunu söylüyor, hücre
  // de boş yere söz vermesin. Yazma reddi (`failure`) listeyi etkilemez.
  const emptyText = error ? "Kullanıcılar okunamadı." : loading ? "Kullanıcılar okunuyor…" : "Henüz kullanıcı yok.";

  const change = (name) => (event) => {
    setForm((current) => ({ ...current, [name]: event.target.value }));
    setFieldErrors((current) => (current[name] ? { ...current, [name]: "" } : current));
    setFlagged((current) => (current === name ? "" : current));
  };

  const add = async () => {
    const invalid = clientErrors(form);
    setFieldErrors(invalid);
    if (Object.keys(invalid).length) return;
    const payload = toPayload(form);
    setAdding(true);
    setFailure("");
    setFlagged("");
    try {
      await api.usersCreate(payload);
      setForm(EMPTY_FORM);
      setNote(`“${payload.username}” eklendi.`);
      onRefresh?.();
    } catch (rejected) {
      // ASSUMPTION: istemci denetimlerini geçmiş bir eklemede sunucunun reddi kullanıcı adına
      // ilişkindir (409 "zaten var"), o yüzden işaret edilecek alan kullanıcı adıdır.
      setFailure(rejected?.message || "Kullanıcı eklenemedi.");
      setFlagged("username");
    } finally {
      setAdding(false);
    }
  };

  // Rol, etkinlik ve parola aynı uçtan geçer. Cümle oturumu düşüren iki işi de söyler, çünkü
  // sunucu parola değişiminde ve pasifleştirmede oturumları siliyor.
  const update = async (user, body, message) => {
    setBusyId(user.id);
    setFailure("");
    try {
      await api.usersUpdate(user.id, body);
      setNote(message);
      onRefresh?.();
    } catch (rejected) {
      setFailure(rejected?.message || "Değişiklik kaydedilemedi.");
    } finally {
      setBusyId(null);
    }
  };

  const openReset = (user) => {
    setResetError("");
    setResetValue("");
    setResetId(resetId === user.id ? null : user.id);
  };

  const saveReset = (user) => {
    if (resetValue.length < PASSWORD_MIN_LEN) {
      setResetError(PASSWORD_MESSAGE);
      return;
    }
    const password = resetValue;
    setResetId(null);
    setResetValue("");
    setResetError("");
    update(user, { password }, `“${user.username}” için parola güncellendi; oturumu kapandı.`);
  };

  return (
    <section id="users-screen" className="screen users-screen">
      <div>
        <h1 className="screen-title">Kullanıcılar</h1>
        <p className="screen-lead">Hesaplar, rolleri ve son girişleri; her değişiklik hemen geçerlidir.</p>
      </div>

      <form
        id="user-add-form"
        className="card user-add-form"
        onSubmit={(event) => {
          event.preventDefault();
          add();
        }}
      >
        <h2 className="rule-form-title">Yeni kullanıcı</h2>
        <div className="user-add-fields">
          <Field
            id="user-new-username"
            label="Kullanıcı adı"
            hint="Küçük harf, rakam, . _ -; 3-32 karakter."
            error={fieldErrors.username}
            invalid={flagged === "username"}
            value={form.username}
            autoComplete="off"
            onChange={change("username")}
          />
          <Field
            id="user-new-password"
            label="Parola"
            hint={`En az ${PASSWORD_MIN_LEN} karakter.`}
            error={fieldErrors.password}
            value={form.password}
            type="password"
            autoComplete="new-password"
            onChange={change("password")}
          />
          <Field
            id="user-new-password2"
            label="Parola (tekrar)"
            hint="Yanlış yazmayı engeller."
            error={fieldErrors.password2}
            value={form.password2}
            type="password"
            autoComplete="new-password"
            onChange={change("password2")}
          />
          <div className="field">
            <label className="field-label" htmlFor="user-new-role">
              Rol
            </label>
            <select
              id="user-new-role"
              className="field-input"
              value={form.role}
              aria-invalid={fieldErrors.role ? "true" : undefined}
              aria-describedby="user-new-role-note"
              onChange={change("role")}
            >
              {ROLES.map((role) => (
                <option value={role} key={role}>
                  {ROLE_LABELS[role] ?? role}
                </option>
              ))}
            </select>
            <p className={fieldErrors.role ? "field-error" : "field-hint"} id="user-new-role-note">
              {fieldErrors.role || "Yönetici kullanıcıları ve iş kurallarını değiştirir."}
            </p>
          </div>
        </div>
        {/* Cevap düğmenin hemen üstünde: iki mesaj üst üste binmesin, kırmızı varsa yeşil susar. */}
        {problem && (
          <p className="users-error" id="users-error" role="alert">
            {problem}
          </p>
        )}
        {!problem && note && <UsersNote>{note}</UsersNote>}
        <div className="user-add-actions">
          <button type="submit" id="user-add-submit" className="btn btn-primary" disabled={adding}>
            {adding ? "Ekleniyor…" : "Kullanıcıyı ekle"}
          </button>
        </div>
      </form>

      <div className="table-wrap">
        <table className="users-table">
          <thead>
            <tr>
              <th scope="col">Kullanıcı</th>
              <th scope="col">Rol</th>
              <th scope="col">Durum</th>
              <th scope="col">Son giriş</th>
              <th scope="col" className="users-col-actions">
                İşlemler
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td className="users-empty" colSpan={5}>
                  {emptyText}
                </td>
              </tr>
            )}
            {rows.map((user) => {
              const busy = busyId === user.id;
              const self = Boolean(selfName) && String(user.username ?? "").toLowerCase() === selfName;
              const login = lastLogin(user.last_login_at);
              return (
                <tr key={user.id}>
                  <th scope="row" className="users-name">
                    {String(user.username ?? "")}
                  </th>
                  <td className="users-role">
                    <select
                      id={`user-role-${user.id}`}
                      className="field-input users-select"
                      aria-label={`${user.username} rolü`}
                      data-user-role={user.id}
                      value={user.role}
                      disabled={busy}
                      onChange={(event) => {
                        const role = event.target.value;
                        if (self && !window.confirm(SELF_ROLE_QUESTION)) return;
                        update(user, { role }, `“${user.username}” rolü güncellendi.`);
                      }}
                    >
                      {ROLES.map((role) => (
                        <option value={role} key={role}>
                          {ROLE_LABELS[role] ?? role}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="users-status">
                    <span className={user.active ? "users-state is-active" : "users-state is-passive"}>
                      {user.active ? "Etkin" : "Pasif"}
                    </span>
                  </td>
                  <td className="users-login" title={login ? undefined : "Hiç giriş yapmadı."}>
                    {login || "—"}
                  </td>
                  <td className="users-actions">
                    {/* Kendi satırında pasifleştirme düğmesi durmaz: sunucu o işte oturumları
                        siliyor, tek tık uygulamanın yöneticisini dışarı atardı (M21 review 4). */}
                    {!self && (
                      <button
                        type="button"
                        className="btn btn-ghost"
                        data-user-toggle={user.id}
                        disabled={busy}
                        onClick={() =>
                          update(
                            user,
                            { active: !user.active },
                            user.active
                              ? `“${user.username}” pasifleştirildi; oturumu kapandı.`
                              : `“${user.username}” etkinleştirildi.`,
                          )
                        }
                      >
                        {user.active ? "Pasifleştir" : "Etkinleştir"}
                      </button>
                    )}
                    <button
                      type="button"
                      className="btn btn-ghost"
                      data-user-reset={user.id}
                      aria-expanded={resetId === user.id}
                      disabled={busy}
                      onClick={() => openReset(user)}
                    >
                      Parolayı değiştir
                    </button>
                    {resetId === user.id && (
                      <span className="users-reset">
                        <input
                          id={`user-reset-${user.id}`}
                          className="field-input"
                          type="password"
                          autoComplete="new-password"
                          aria-label={`${user.username} için yeni parola`}
                          placeholder={`En az ${PASSWORD_MIN_LEN} karakter`}
                          value={resetValue}
                          aria-invalid={resetError ? "true" : undefined}
                          onChange={(event) => {
                            setResetValue(event.target.value);
                            setResetError("");
                          }}
                        />
                        <button
                          type="button"
                          className="btn btn-primary"
                          data-user-reset-save={user.id}
                          onClick={() => saveReset(user)}
                        >
                          Kaydet
                        </button>
                        {resetError && <p className="field-error">{resetError}</p>}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
