import { useEffect, useReducer, useState } from "react";
import AnswerCard from "./components/AnswerCard.jsx";
import AskBox from "./components/AskBox.jsx";
import ClarificationCard from "./components/ClarificationCard.jsx";
import EmptyState from "./components/EmptyState.jsx";
import ErrorCard from "./components/ErrorCard.jsx";
import LoadingSteps from "./components/LoadingSteps.jsx";
import { MapFlow } from "./components/MapScreen.jsx";
import MastheadNav from "./components/MastheadNav.jsx";
import RulesScreen from "./components/RulesScreen.jsx";
import Sidebar from "./components/Sidebar.jsx";
import UsersScreen from "./components/UsersScreen.jsx";
import * as api from "./lib/api.js";
import { askReducer, initialState } from "./lib/askState.js";
import { NOT_ALLOWED_NOTE, ROLE_LABELS, canSee } from "./lib/auth.js";
import { parseRoute } from "./lib/route.js";
import { applyTheme, nextTheme, readStored, store } from "./lib/theme.js";

// Düğmenin gördüğü ad, sıradaki temayı değil seçili olanı söyler: "Koyu" yazan bir düğmeye
// basınca ne olacağı belirsiz kalmasın.
const HEALTH_URL = "/api/health";
const THEME_LABELS = { system: "Sistem", dark: "Koyu", light: "Açık" };

// Testler App'i Node'da renderToStaticMarkup ile kuruyor: orada localStorage yoktur, tema da
// okunacak bir yer bulamayınca "system"de kalır.
function themeStorage() {
  try {
    return localStorage ?? null;
  } catch {
    return null;
  }
}

// Testler renderToStaticMarkup ile node'da çalıştırıyor: orada window yok, kök varsayılan rotada açılır.
function currentHash() {
  return typeof window === "undefined" ? "" : window.location.hash;
}

// Her halin bir de sözcüğü var: 10px'lik daire tek başına anlamını yalnız ipucunda taşıyordu.
export function healthDot(health) {
  if (!health) {
    return { tone: "unknown", label: "Bilinmiyor", tip: "Durum alınamadı: sunucu çalışmıyor olabilir." };
  }
  if (health.llm && health.llm.reachable === false) {
    return {
      tone: "down",
      label: "Kapalı",
      tip: `Model yanıt vermiyor${health.llm.reason ? `: ${health.llm.reason}` : "."}`,
    };
  }
  if (health.index && health.index.fresh === false) {
    return { tone: "stale", label: "Bayat", tip: `İndeks eski${health.index.reason ? `: ${health.index.reason}` : "."}` };
  }
  return { tone: "ok", label: "Hazır", tip: "Hazır: model erişilebilir, indeks taze." };
}

// Çip iki yuvaya ayrılır: veri kümesinin kendi adı, ardından niteliği (parantez içi ve model).
// Telefon başlığında nitelik gizlenir — hangi veritabanından söz edildiğini söyleyen tek yer bu
// çip, kırpılan taraf adı olmamalı. `full` başlıkta durur: ekranda görünmeyince kaybolmaz.
function chipParts(health) {
  const full = [health?.dataset?.display_name, health?.llm?.model].filter(Boolean).join(" · ");
  const paren = full.match(/^(.+?)\s+\([^()]*\)/);
  const name = paren ? paren[1] : full.split(" · ")[0];
  return { full, name, note: full.slice(name.length) };
}

// Rol adı hiç okunamazsa çip yalnız kullanıcı adını taşır: "undefined" bir kimlik değildir.
function userLabel(user) {
  return [user?.username, ROLE_LABELS[user?.role]].filter(Boolean).join(" · ");
}

// Soru ekranı: akışın halleri burada birbirine bağlanır (R5-18). Boş, bekleyen, cevap,
// netleştirme ve hata yuvaları burada durur; cevabın grafiği kartın içindedir.
function AskScreen({ pending = null, onRefresh, onRebuild, datasetKey = 0, canEditRules = false }) {
  const [state, dispatch] = useReducer(askReducer, initialState);
  const [text, setText] = useState("");
  const [examples, setExamples] = useState([]);
  const [rulesEmpty, setRulesEmpty] = useState(false);

  // `datasetKey` her küme değişiminde büyür: örnekler kümenin sorularıdır, eski kümenin çipleri
  // yeni veritabanının üstünde kalırsa ekran yalan söylemiş olur.
  useEffect(() => {
    let mounted = true;
    api
      .examples()
      .then((data) => mounted && setExamples(Array.isArray(data?.examples) ? data.examples : []))
      .catch(() => {
        // örnekler gelmezse boş ekran kendi iki cümlesiyle de açık kalır
      });
    return () => {
      mounted = false;
    };
  }, [datasetKey]);

  // ASSUMPTION: kutunun "kural da yok" demesinin kaynağı /api/rules; sayı yalnız çipler yokken
  // sorulur, çünkü cümlenin ikinci yarısı o durumda görünür. Yeni haritalanmış kümede ikisi de yoktur.
  useEffect(() => {
    if (examples.length > 0) return;
    let mounted = true;
    api
      .rulesList()
      .then((payload) =>
        mounted && setRulesEmpty((Array.isArray(payload?.rules) ? payload.rules : []).length === 0),
      )
      .catch(() => {
        // sayı okunamazsa cümle yalnız örnek soru tarafını söyler
      });
    return () => {
      mounted = false;
    };
  }, [examples]);

  // auditId verilirse soru modele baştan sorulmaz: geçmişteki SQL yeniden çalışır (/api/replay).
  const send = (question, choice = null, auditId = null) => {
    const asked = String(question ?? "").trim();
    if (!asked) return;
    dispatch({ type: "ask", question: asked, choice });
    (auditId ? api.replay(auditId) : api.ask({ question: asked, choice }))
      .then((payload) => dispatch({ type: "receive", payload }))
      .catch((error) =>
        dispatch({
          type: "fail",
          kind: error?.status === 0 ? "network" : "failed",
          message: error?.message ?? "",
        }),
      )
      // Soru neyle biterse bitsin günlüğe bir satır düşer: kenar çubuğu her durumda tazelenir.
      .finally(() => onRefresh?.());
  };

  // Kenar çubuğundan gelen soru, kutudan sorulmuş gibi koşar; sayaç aynı sorunun ikinci
  // tıklayışını da yeni bir istek yapar.
  // Soru kutuya da yazılır ve ekran kutuya kayar: yoksa kutuda eski metin kalır, bekleme adımları
  // ve cevap ekranın altında açılır, tıklama hiçbir şey yapmamış gibi görünür (2026-10-25).
  useEffect(() => {
    if (!pending?.question) return;
    setText(pending.question);
    send(pending.question, null, pending.auditId ?? null);
    document.getElementById("main")?.scrollIntoView?.({ block: "start", behavior: "smooth" });
  }, [pending]);

  // Çip soruyu kutuya yazar ve bekletmeden sorar (R5-18).
  const ask = (question) => {
    setText(question ?? "");
    send(question);
  };

  // Seçenek, sorunun hangi anlamla koşulacağını sabitler: aynı soru choice ile yeniden koşar (R5-11).
  const choose = (option) => send(state.question, option);

  // "Soruyu değiştir" kartı kapatmaz: imleç kutuya döner, kullanıcı yazıp yeniden sorar.
  const changeQuestion = () => document.getElementById("question")?.focus();

  // Kayıt kenar çubuğunun listesine de düşer.
  const save = (item) =>
    api.savedAdd(item).then((result) => {
      onRefresh?.();
      return result;
    });

  const loading = state.status === "loading";
  const failed = state.status === "failed" || state.status === "network_error";

  return (
    <section className="screen ask-flow">
      <AskBox
        value={text}
        onChange={setText}
        onAsk={ask}
        loading={loading}
        examples={state.status === "idle" ? [] : examples}
      />
      {state.status === "idle" && (
        <EmptyState examples={examples} rulesHint={canEditRules && rulesEmpty} onSelect={ask} />
      )}
      {loading && <LoadingSteps />}
      {state.status === "answered" && (
        <AnswerCard payload={state.payload} choice={state.choice} onSave={save} />
      )}
      {state.status === "clarifying" && (
        <ClarificationCard payload={state.payload} onChoose={choose} onChange={changeQuestion} />
      )}
      {failed && <ErrorCard kind={state.error?.kind} message={state.error?.message} onRebuild={onRebuild} />}
    </section>
  );
}

// Kural ekranı: liste ile indeksin tazeliği aynı iki istekten gelir; kayıt, silme ve yeniden
// kurma sonrası ekran bunları baştan okur (R5-16).
function RulesFlow({ onChanged, readOnly }) {
  const [data, setData] = useState(null); // {rules, index} | null: henüz okunmadı
  const [tables, setTables] = useState([]);
  const [error, setError] = useState("");

  const refresh = () => {
    api
      .rulesList()
      .then((payload) =>
        setData({
          rules: Array.isArray(payload?.rules) ? payload.rules : [],
          index: payload?.index ?? null,
        }),
      )
      .catch((failure) => setError(failure?.message || "Kurallar okunamadı."));
    api
      .tables()
      .then((payload) => setTables(Array.isArray(payload?.tables) ? payload.tables : []))
      .catch(() => {
        // tablo adları yalnızca datalist'i doldurur; boş listeyle de yazılabilir
      });
    // Bantla başlıktaki nokta aynı `index.fresh`i gösterir: bant tazelendiği an nokta da tazelenir.
    onChanged?.();
  };

  useEffect(refresh, []);

  return (
    <RulesScreen
      rules={data?.rules ?? []}
      index={data?.index ?? null}
      tables={tables}
      loading={!data}
      error={error}
      onRefresh={refresh}
      readOnly={readOnly}
    />
  );
}

// Kullanıcı ekranı: yöneticinin defteri tek istekten okunur; her ekme ve güncelleme sonrası
// ekran aynı isteği yineler, böylece tablo sunucudaki halini gösterir (R6-19).
function UsersFlow({ currentUser }) {
  const [users, setUsers] = useState(null); // null: henüz okunmadı
  const [error, setError] = useState("");

  const refresh = () => {
    api
      .usersList()
      .then((payload) => setUsers(Array.isArray(payload?.users) ? payload.users : []))
      .catch((failure) => setError(failure?.message || "Kullanıcılar okunamadı."));
  };

  useEffect(refresh, []);

  // `currentUser` oturum sahibinin kendisi: kendi satırındaki düğmeler buna göre ayıklanır.
  return (
    <UsersScreen users={users ?? []} currentUser={currentUser} loading={!users} error={error} onRefresh={refresh} />
  );
}

function Screen({
  route,
  pending,
  onRefresh,
  onChanged,
  onRebuild,
  onSwitched,
  datasetKey,
  readOnly,
  currentUser,
}) {
  if (route === "rules") return <RulesFlow onChanged={onChanged} readOnly={readOnly} />;
  if (route === "users") return <UsersFlow currentUser={currentUser} />;
  if (route === "map") return <MapFlow onSwitched={onSwitched} />;
  return (
    <AskScreen
      pending={pending}
      onRefresh={onRefresh}
      onRebuild={onRebuild}
      datasetKey={datasetKey}
      canEditRules={!readOnly}
    />
  );
}

// `user` ve `onLogout` oturum kapısı Root'tan gelir; ikisi de yoksa kabuk Run 5'teki gibi
// tek kullanıcılıdır (oturum yok, çıkış yok). `note` kapının düşürdüğü ekranın cümlesidir.
export default function App({ user = null, onLogout = null, note = "" }) {
  const [hash, setHash] = useState(currentHash);
  const [health, setHealth] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [saved, setSaved] = useState([]);
  const [history, setHistory] = useState([]);
  const [pending, setPending] = useState(null); // {question, n}: kenar çubuğundan gelen soru
  const [datasetKey, setDatasetKey] = useState(0); // her küme değişiminde büyür, örnekler tazelenir
  const [theme, setTheme] = useState(() => readStored(themeStorage()));
  // Adres rolle çözülür: `#/kullanicilar` ile açan ya da yenileyen sıradan bir kullanıcı yönetici
  // defterini görmez, kapının girişte yaptığı gibi soru ekranına bir cümleyle düşer. Kullanıcı yoksa
  // kabuk tek kullanıcılıdır ve Run 5'teki gibi her ekran açıktır.
  const requested = parseRoute(hash);
  const allowed = !user || canSee(requested, user.role);
  const route = allowed ? requested : "ask";
  const screenNote = note || (allowed ? "" : NOT_ALLOWED_NOTE);

  // Kök nitelik seçili temayı taşısın: açılışta bir kez, her değişimde yeniden. main.jsx ilk
  // boyamadan önce aynı işi yaptığı için koyu teması olan açılışta açık bir kare görmez.
  useEffect(() => applyTheme(document, theme), [theme]);

  const cycleTheme = () => {
    const next = nextTheme(theme);
    setTheme(next);
    store(themeStorage(), next);
  };

  useEffect(() => {
    const onHashChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  // Sağlık başlığı bir kez değil, aynı `index.fresh` alanını gösteren yer değiştikçe okunur:
  // kural ekranının bandı tazelenirken noktanın eski kalması arayüzün aynı gerçeği iki yerden
  // birini yalan söylemesi olurdu (R5-18).
  // Ham fetch değil api.health: 401 de buradan geçer, oturum düştüğünde kök kapı haberdar olur.
  const refreshHealth = () => {
    api
      .health(HEALTH_URL)
      .then((data) => setHealth(data))
      .catch(() => setHealth(null));
  };

  useEffect(() => refreshHealth(), []);

  // Kenar çubuğunun iki listesi her soru, kayıt ve silme sonrası baştan okunur; düşerse
  // ekranın kendi verisi olduğu için burada dururlar.
  const refresh = () => {
    api
      .savedList()
      .then((data) => setSaved(Array.isArray(data?.saved) ? data.saved : []))
      .catch(() => {
        // liste gelmezse kenar çubuğu son bildiğini göstermeye devam eder
      });
    api
      .history()
      .then((data) => setHistory(Array.isArray(data?.history) ? data.history : []))
      .catch(() => {});
  };

  useEffect(() => {
    refresh();
  }, []);

  // Etkin küme değiştiği an, aynı gerçeği gösteren her yer baştan okunur: başlıktaki çip
  // (health), kenar çubuğunun iki listesi ve soru ekranının örnekleri.
  const switched = () => {
    refreshHealth();
    refresh();
    setDatasetKey((key) => key + 1);
  };

  // Satıra tıklayınca soru soru ekranında koşar; dar ekranda çekmece kapanır ki cevap görünsün.
  const askFromSidebar = (question, auditId = null) => {
    setPending((current) => ({ question, auditId, n: (current?.n ?? 0) + 1 }));
    setSidebarOpen(false);
    if (route !== "ask") window.location.hash = "#/";
  };

  // Çıkış önce sunucudaki oturumu kapatır; kök kapı App'i kaldırdığı için cevap, geçmiş ve kural
  // durumları da ekrandan kalkar. Kapanış isteği başarısız olsa da kullanıcı içeride tutulmaz.
  const logout = () => api.logout().catch(() => null).then(() => onLogout());

  const dot = healthDot(health);
  const chip = chipParts(health);
  const who = userLabel(user);

  return (
    <div className="app">
      <header className="masthead">
        <a className="wordmark" href="#/">
          Bilgin
        </a>
        {chip.full && (
          <span
            className="chip"
            id="model-chip"
            title={[chip.full, health?.llm?.url].filter(Boolean).join(" · ")}
          >
            {chip.name}
            {chip.note && <span className="chip-note">{chip.note}</span>}
          </span>
        )}
        <MastheadNav route={route} user={user} />
        <button
          type="button"
          id="theme-toggle"
          className="btn btn-theme"
          aria-label={`Tema: ${THEME_LABELS[theme]}. Değiştirmek için etkinleştir.`}
          onClick={cycleTheme}
        >
          {THEME_LABELS[theme]}
        </button>
        {/* Sözcük noktanın yanında: ipucu kümenin tamamına, adlandırma noktaya ait kalır. */}
        <span className="health" title={dot.tip}>
          <span className={`dot dot-${dot.tone}`} role="img" aria-label={dot.tip} />
          <span id="health-label">{dot.label}</span>
        </span>
        {who && (
          <span className="chip" id="user-chip" title="Oturum sahibi">
            {who}
          </span>
        )}
        {onLogout && (
          <button type="button" id="logout" className="btn btn-ghost" onClick={logout}>
            Çıkış
          </button>
        )}
      </header>
      <div className="shell">
        <button
          type="button"
          id="sidebar-toggle"
          className="sidebar-toggle"
          aria-expanded={sidebarOpen}
          aria-controls="sidebar"
          onClick={() => setSidebarOpen((open) => !open)}
        >
          Kayıtlılar ve geçmiş
        </button>
        <aside id="sidebar" className={sidebarOpen ? "sidebar is-open" : "sidebar"} aria-label="Kayıtlılar ve geçmiş">
          {/* Çekmece ekranı doldurup tek kapatma düğmesini (toggle'ı) listenin üstünde ekrandan
              çıkarıyordu: açık panel kendi düğmesini tepesinde taşır (M22 görsel inceleme 5). */}
          {sidebarOpen && (
            <button
              type="button"
              id="sidebar-close"
              className="sidebar-close"
              aria-controls="sidebar"
              onClick={() => setSidebarOpen(false)}
            >
              Kapat
            </button>
          )}
          <Sidebar saved={saved} history={history} onAsk={askFromSidebar} onRemoved={refresh} />
        </aside>
        <main id="main">
          {/* Cümle düşülen ekranın üstünde durur; başka bir ekrana geçince kendiliğinden kalkar. */}
          {screenNote && route === "ask" && (
            <p className="route-note" id="route-note">
              {screenNote}
            </p>
          )}
          <Screen
            route={route}
            pending={pending}
            onRefresh={refresh}
            onChanged={refreshHealth}
            onRebuild={() => api.rebuild().then(refreshHealth)}
            onSwitched={switched}
            datasetKey={datasetKey}
            readOnly={Boolean(user && user.role !== "admin")}
            currentUser={user}
          />
        </main>
      </div>
    </div>
  );
}
