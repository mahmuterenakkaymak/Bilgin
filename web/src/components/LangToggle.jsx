import { useEffect } from "react";
import { SUPPORTED, useT } from "../i18n/index.js";
import * as api from "../lib/api.js";
import { storeLang } from "../lib/lang.js";

// R8-16: arayüz dilinin tek düğmesi. Görünen ad dilin iki harfli kodu, erişilebilir adı
// katalogun cümlesi: "İngilizce"yi İngilizce arayan da aynı düğmeyi okur. Dil provider'da
// yaşadığı için seçim ekranı yeniden yüklemeden çevirir; sunucunun üretip ekrana konmuş metni
// (cevap, uyarı) kendi dilinde kalır — R8-16'nın istediği de bu.
export default function LangToggle({ user = null }) {
  const { t, lang, setLang } = useT();

  // Kök nitelik ve istek başlığı seçilen dili taşır: ilki tarayıcıya telaffuzu, ikincisi
  // sunucuya hangi dille cevap verileceğini söyler. Açılışta main.jsx ikisini de yazdı; burası
  // seçimden sonrakileri taşır.
  useEffect(() => {
    document.documentElement.lang = lang;
    api.setApiLang(lang);
  }, [lang]);

  const pick = (code) => {
    if (code === lang) return;
    setLang(code);
    storeLang(code);
    // Tercih kişinin kendi sunucudaki satırına da yazılır; giriş kartında oturum yoktur, dil o
    // durumda yalnız yerelde durur ve girişte `me.lang` onu zaten ezer.
    if (user) api.setMyLang(code).catch(() => {});
  };

  return (
    <div id="lang-toggle" className="lang-toggle" role="group" aria-label={t("lang.group")}>
      {SUPPORTED.map((code) => (
        <button
          key={code}
          type="button"
          className="lang-option"
          data-lang={code}
          aria-pressed={code === lang}
          aria-label={t(`lang.${code}`)}
          onClick={() => pick(code)}
        >
          {code.toUpperCase()}
        </button>
      ))}
    </div>
  );
}
