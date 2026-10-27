import { useState } from "react";
import { useT } from "../i18n/index.js";
import * as api from "../lib/api.js";
import { BUSINESS_ROLES, roleLabel } from "../lib/startCards.js";
import { MESSAGE_KEYS, PASSWORD_MIN_LEN, ROLES, clientErrors, toPayload } from "../lib/usersForm.js";

// Kullanıcı ekranı (R6-19): yöneticinin defteri. Liste üstten okunur; her ekme ve güncelleme
// sonrası aynı istek yinelenir ki tablo sunucudaki halini göstersin. Reddin cümlesi değiştirilmeden
// #users-error'a düşer — son etkin yöneticiyi koruyan 409'un sözü de sunucunundur.
// nl2sql/config.DEFAULT_BUSINESS_ROLE: arayüz Python'u okuyamadığı için varsayılan burada da duruyor.
const DEFAULT_BUSINESS_ROLE = "genel";

const EMPTY_FORM = { username: "", password: "", password2: "", role: "user", businessRole: DEFAULT_BUSINESS_ROLE };

// Kendi rolü tek tıkla düşmez: değişince yönetici ekranları kapanır, o yüzden önce söz istenir
// (cümleler kataloğunda, R8-20; sunucunun reddi kendi diliyle geldiği için olduğu gibi okunur).
// Rol adları da katalogdan: `lib/auth.js` ve `lib/startCards.js` Türkçe sabitlerini kendi
// ekranları için taşıyor, tanınmayan kod kendi adıyla kalır.
const ROLE_KEYS = { admin: "role.admin", user: "role.user" };
const BUSINESS_ROLE_KEYS = {
  satis: "role.satis",
  satin_alma: "role.satin_alma",
  muhasebe: "role.muhasebe",
  yonetim: "role.yonetim",
  genel: "role.genel",
};

const LOCALES = { tr: "tr-TR", en: "en-US" };

// ASSUMPTION: "Son giriş" tarayıcının yerel saatiyle okunur; sunucu UTC yazıyor, dilim yalnız gösterim.
function lastLogin(value, lang) {
  const date = new Date(typeof value === "string" ? value : Number.NaN);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString(LOCALES[lang] ?? LOCALES.tr, {
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
  const { t, lang } = useT();
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
  const emptyText = error ? t("users.loadFailed") : loading ? t("users.empty.loading") : t("users.empty.none");

  const change = (name) => (event) => {
    setForm((current) => ({ ...current, [name]: event.target.value }));
    setFieldErrors((current) => (current[name] ? { ...current, [name]: "" } : current));
    setFlagged((current) => (current === name ? "" : current));
  };

  const add = async () => {
    const invalid = clientErrors(form, lang);
    setFieldErrors(invalid);
    if (Object.keys(invalid).length) return;
    // İş rolü formda `businessRole` adıyla duruyor (React alanı), API'nin beklediği anahtar ise
    // `business_role`; `toPayload`ın şekli usersForm.test.js'de sabit, o yüzden burada ekleniyor.
    const payload = { ...toPayload(form), business_role: form.businessRole };
    setAdding(true);
    setFailure("");
    setFlagged("");
    try {
      await api.usersCreate(payload);
      setForm(EMPTY_FORM);
      setNote(t("users.added", { name: payload.username }));
      onRefresh?.();
    } catch (rejected) {
      // ASSUMPTION: istemci denetimlerini geçmiş bir eklemede sunucunun reddi kullanıcı adına
      // ilişkindir (409 "zaten var"), o yüzden işaret edilecek alan kullanıcı adıdır.
      setFailure(rejected?.message || t("users.addFailed"));
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
      setFailure(rejected?.message || t("users.saveFailed"));
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
      setResetError(t(MESSAGE_KEYS.password, { min: PASSWORD_MIN_LEN }));
      return;
    }
    const password = resetValue;
    setResetId(null);
    setResetValue("");
    setResetError("");
    update(user, { password }, t("users.reset.saved", { name: user.username }));
  };

  return (
    <section id="users-screen" className="screen users-screen">
      <div>
        <h1 className="screen-title">{t("users.title")}</h1>
        <p className="screen-lead">{t("users.lead")}</p>
      </div>

      <form
        id="user-add-form"
        className="card user-add-form"
        onSubmit={(event) => {
          event.preventDefault();
          add();
        }}
      >
        <h2 className="rule-form-title">{t("users.newTitle")}</h2>
        <div className="user-add-fields">
          <Field
            id="user-new-username"
            label={t("users.field.username")}
            hint={t("users.hint.username")}
            error={fieldErrors.username}
            invalid={flagged === "username"}
            value={form.username}
            autoComplete="off"
            onChange={change("username")}
          />
          <Field
            id="user-new-password"
            label={t("users.field.password")}
            hint={t("users.hint.password", { min: PASSWORD_MIN_LEN })}
            error={fieldErrors.password}
            value={form.password}
            type="password"
            autoComplete="new-password"
            onChange={change("password")}
          />
          <Field
            id="user-new-password2"
            label={t("users.field.password2")}
            hint={t("users.hint.password2")}
            error={fieldErrors.password2}
            value={form.password2}
            type="password"
            autoComplete="new-password"
            onChange={change("password2")}
          />
          <div className="field">
            <label className="field-label" htmlFor="user-new-role">
              {t("users.field.role")}
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
                  {t(ROLE_KEYS[role])}
                </option>
              ))}
            </select>
            <p className={fieldErrors.role ? "field-error" : "field-hint"} id="user-new-role-note">
              {fieldErrors.role || t("users.hint.role")}
            </p>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="user-new-business-role">
              {t("users.field.businessRole")}
            </label>
            <select
              id="user-new-business-role"
              className="field-input"
              value={form.businessRole}
              aria-describedby="user-new-business-role-note"
              onChange={change("businessRole")}
            >
              {BUSINESS_ROLES.map((item) => (
                <option value={item.role} key={item.role}>
                  {t(BUSINESS_ROLE_KEYS[item.role])}
                </option>
              ))}
            </select>
            <p className="field-hint" id="user-new-business-role-note">
              {t("users.hint.businessRole")}
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
            {adding ? t("users.adding") : t("users.add")}
          </button>
        </div>
      </form>

      <div className="table-wrap">
        <table className="users-table">
          <thead>
            <tr>
              <th scope="col">{t("users.col.user")}</th>
              <th scope="col">{t("users.col.role")}</th>
              <th scope="col">{t("users.col.businessRole")}</th>
              <th scope="col">{t("users.col.status")}</th>
              <th scope="col">{t("users.col.lastLogin")}</th>
              <th scope="col" className="users-col-actions">
                {t("users.col.actions")}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td className="users-empty" colSpan={6}>
                  {emptyText}
                </td>
              </tr>
            )}
            {rows.map((user) => {
              const busy = busyId === user.id;
              const self = Boolean(selfName) && String(user.username ?? "").toLowerCase() === selfName;
              const login = lastLogin(user.last_login_at, lang);
              // İş rolü Run 7'nin alanı: eski bir listede hiç olmayabilir, o zaman sunucunun
              // varsayılanı okunur; listede olmayan kod ilk seçenek olarak düşmesin, kendi adıyla dursun.
              const listed = typeof user.business_role === "string" ? user.business_role : "";
              const business = listed || DEFAULT_BUSINESS_ROLE;
              const extraRole = BUSINESS_ROLES.some((item) => item.role === business) ? [] : [business];
              return (
                <tr key={user.id}>
                  <th scope="row" className="users-name">
                    {String(user.username ?? "")}
                  </th>
                  <td className="users-role">
                    <select
                      id={`user-role-${user.id}`}
                      className="field-input users-select"
                      aria-label={t("users.row.roleAria", { name: user.username })}
                      data-user-role={user.id}
                      value={user.role}
                      disabled={busy}
                      onChange={(event) => {
                        const role = event.target.value;
                        if (self && !window.confirm(t("users.selfRoleConfirm"))) return;
                        update(user, { role }, t("users.roleUpdated", { name: user.username }));
                      }}
                    >
                      {ROLES.map((role) => (
                        <option value={role} key={role}>
                          {t(ROLE_KEYS[role])}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="users-business">
                    {/* Alan kendi satırında kapalı: sunucu bu işe 403 diyor, tek tık boşuna denemez. */}
                    <select
                      id={`user-business-role-${user.id}`}
                      className="field-input users-select"
                      aria-label={t("users.row.businessRoleAria", { name: user.username })}
                      data-user-business-role={user.id}
                      value={business}
                      disabled={busy || self}
                      title={self ? t("users.ownBusinessRole") : undefined}
                      onChange={(event) =>
                        update(
                          user,
                          { business_role: event.target.value },
                          t("users.businessRoleUpdated", { name: user.username }),
                        )
                      }
                    >
                      {BUSINESS_ROLES.map((item) => (
                        <option value={item.role} key={item.role}>
                          {t(BUSINESS_ROLE_KEYS[item.role])}
                        </option>
                      ))}
                      {extraRole.map((role) => (
                        <option value={role} key={role}>
                          {roleLabel(role)}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="users-status">
                    <span className={user.active ? "users-state is-active" : "users-state is-passive"}>
                      {user.active ? t("users.status.active") : t("users.status.passive")}
                    </span>
                  </td>
                  <td className="users-login" title={login ? undefined : t("users.neverLoggedIn")}>
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
                              ? t("users.deactivated", { name: user.username })
                              : t("users.activated", { name: user.username }),
                          )
                        }
                      >
                        {user.active ? t("users.deactivate") : t("users.activate")}
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
                      {t("users.reset")}
                    </button>
                    {resetId === user.id && (
                      <span className="users-reset">
                        <input
                          id={`user-reset-${user.id}`}
                          className="field-input"
                          type="password"
                          autoComplete="new-password"
                          aria-label={t("users.reset.aria", { name: user.username })}
                          placeholder={t("users.reset.placeholder", { min: PASSWORD_MIN_LEN })}
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
                          {t("users.reset.save")}
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
