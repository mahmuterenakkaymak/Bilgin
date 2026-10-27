import { useState } from "react";
import { useT } from "../i18n/index.js";
import LangToggle from "./LangToggle.jsx";

// Giriş kartı: kararı (hangi ekran, hangi not) Root verir, ağ işini de oradan alır. Ekran
// yalnız iki alanı, göndermeyi ve hatanın kendisini taşır; başarısız giriş formu kapatmaz.
export default function LoginScreen({ note = "", onLogin }) {
  const { t } = useT();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event) => {
    event.preventDefault();
    if (sending) return;
    setError("");
    setSending(true);
    try {
      // Başarılı girişte Root ekranı App'e çevirir, bu bileşen kapanır: hâlâ tutulan bir şey yok.
      await onLogin({ username, password });
    } catch (failure) {
      // Reddin cümlesi sunucudan kişinin dilinde gelir (`detail`); başlıksız hata katalogdakine düşer.
      setError(failure?.message || t("login.failed"));
      setSending(false);
    }
  };

  return (
    <div className="gate">
      <form id="login-form" className="login-card" onSubmit={submit}>
        {/* Kartı ilk kez açan da dilini seçebilsin: cümleler oturumdan önce çevrilir. Tercih
            yerelde durur, girişten sonra kişinin kayıtlı dili onu ezer. */}
        <LangToggle />
        {/* alt boş: işaret adın resmi, hemen altında "Bilgin" zaten okunuyor — iki kez söylenmez. */}
        <img className="login-mark" src="/assets/bilgin.svg" alt="" width="44" height="44" />
        <h1 className="login-title">{t("login.title")}</h1>
        <p className="login-lead">{t("login.lead")}</p>
        {/* Kartın ne açtığını ilk kez gelen de bilsin: sabit bir cümle, adresi yok, veri seti
            adı yok — ziyaretçi henüz kim olduğunu kanıtlamadı.
            ASSUMPTION: İngilizce sürüm "Türkçe" sözcüğünü taşımaz — soru dili artık ikisi de. */}
        <p className="login-tagline" id="login-tagline">
          {t("login.tagline")}
        </p>
        {/* ASSUMPTION: not, sunucunun `detail`i ya da lib/auth'un cümlesidir; kendi dilinde
            gelir ve burada çevrilmeden gösterilir. */}
        {note && <p className="login-note" id="login-note">{note}</p>}
        <div className="field">
          <label className="field-label" htmlFor="login-username">
            {t("login.username")}
          </label>
          <input
            id="login-username"
            className="field-input"
            type="text"
            autoComplete="username"
            autoFocus
            required
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            disabled={sending}
            aria-describedby={error ? "login-error" : undefined}
          />
        </div>
        <div className="field">
          <label className="field-label" htmlFor="login-password">
            {t("login.password")}
          </label>
          <input
            id="login-password"
            className="field-input"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={sending}
            aria-describedby={error ? "login-error" : undefined}
          />
        </div>
        {error && (
          <p className="login-error" id="login-error" role="alert">
            {error}
          </p>
        )}
        <button type="submit" id="login-submit" className="btn btn-primary login-submit" disabled={sending}>
          {sending ? t("login.submitting") : t("login.submit")}
        </button>
      </form>
    </div>
  );
}
