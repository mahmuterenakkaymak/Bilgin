import { useEffect, useState } from "react";
import App from "./App.jsx";
import LoginScreen from "./components/LoginScreen.jsx";
import * as api from "./lib/api.js";
import { EXPIRED_NOTE, afterLogin, boot } from "./lib/auth.js";

// route.js'in tersi: girişten sonra varılacak ekranın adresi. Yalnız burada gerekiyor, o yüzden
// küçük bir tablo olarak kapının yanında duruyor.
const HASHES = { ask: "#/", rules: "#/kurallar", map: "#/harita", users: "#/kullanicilar" };

// Testler Root'u Node'da kuruyor: orada window yoktur, kapı kök adresteymiş gibi açılır.
function currentHash() {
  return typeof window === "undefined" ? "" : window.location.hash;
}

// Oturum kapısı: üç halden yalnız biri boyanır. Cevap, geçmiş ve kural durumları App'in içinde
// yaşadığı için çıkışta ya da oturum düşünce hepsi ekrandan kalkar; geriye yalnız kart kalır.
// `initial` yalnız testin kapıyı belirli bir halden kurması için (renderToStaticMarkup effect çalıştırmaz).
export default function Root({ initial = null }) {
  const [state, setState] = useState(initial ?? { screen: "checking" });

  // Açılış tek bir `me` isteğidir: 401 giriş ekranıdır, oturum ise istenen adreste uygulama.
  useEffect(() => {
    if (initial) return;
    let mounted = true;
    boot(api, currentHash())
      .then((next) => mounted && setState(next))
      .catch((failure) =>
        // Kapının kararı olmayan hata (sunucuya ulaşılamıyor) giriş ekranında bir cümleyle karşılık bulur.
        mounted &&
        setState({
          screen: "login",
          user: null,
          requested: currentHash(),
          note: failure?.message || "Sunucuya ulaşılamadı.",
        }),
      );
    return () => {
      mounted = false;
    };
  }, [initial]);

  // 401 bekçisi yalnız uygulama ayaktayken kurulu: açılıştaki 401 "oturum yok"tur, "oturum düştü" değil.
  useEffect(() => {
    if (state.screen !== "app") return () => api.onUnauthorized(null);
    api.onUnauthorized(() =>
      setState({ screen: "login", user: null, requested: currentHash(), note: EXPIRED_NOTE }),
    );
    return () => api.onUnauthorized(null);
  }, [state.screen]);

  const login = async ({ username, password }) => {
    const user = await api.login({ username, password });
    const next = afterLogin(user, state.requested);
    // Adır hedefe göre ayarlanır: App yeni adreste açılır, adres çubuğu da onu gösterir.
    if (typeof window !== "undefined") window.location.hash = HASHES[next.route] ?? "#/";
    setState({ screen: "app", user, route: next.route, requested: state.requested, note: next.note });
  };

  const logout = () => setState({ screen: "login", user: null, requested: currentHash(), note: "" });

  if (state.screen === "checking") {
    return (
      <div className="gate">
        <span className="wordmark">Bilgin</span>
      </div>
    );
  }

  if (state.screen === "login") {
    return <LoginScreen note={state.note ?? ""} onLogin={login} />;
  }

  return <App user={state.user} onLogout={logout} note={state.note ?? ""} />;
}
