import { useEffect, useReducer, useState } from "react";
import AnswerCard from "./components/AnswerCard.jsx";
import AskBox from "./components/AskBox.jsx";
import ChartView from "./components/ChartView.jsx";
import ClarificationCard from "./components/ClarificationCard.jsx";
import EmptyState from "./components/EmptyState.jsx";
import ErrorCard from "./components/ErrorCard.jsx";
import LoadingSteps from "./components/LoadingSteps.jsx";
import RulesScreen from "./components/RulesScreen.jsx";
import Sidebar from "./components/Sidebar.jsx";
import * as api from "./lib/api.js";
import { askReducer, initialState } from "./lib/askState.js";
import { parseRoute } from "./lib/route.js";

const HEALTH_URL = "/api/health";

// Testler renderToStaticMarkup ile node'da çalıştırıyor: orada window yok, kök varsayılan rotada açılır.
function currentHash() {
  return typeof window === "undefined" ? "" : window.location.hash;
}

function healthDot(health) {
  if (!health) return { tone: "unknown", tip: "Durum alınamadı: sunucu çalışmıyor olabilir." };
  if (health.llm && health.llm.reachable === false) {
    return { tone: "down", tip: `Model yanıt vermiyor${health.llm.reason ? `: ${health.llm.reason}` : "."}` };
  }
  if (health.index && health.index.fresh === false) {
    return { tone: "stale", tip: `İndeks eski${health.index.reason ? `: ${health.index.reason}` : "."}` };
  }
  return { tone: "ok", tip: "Hazır: model erişilebilir, indeks taze." };
}

function chipText(health) {
  if (!health) return "";
  return [health.dataset?.display_name, health.llm?.model].filter(Boolean).join(" · ");
}

// Soru ekranı: akışın halleri burada birbirine bağlanır (R5-18). Boş, bekleyen, cevap,
// netleştirme ve hata yuvaları ile cevabın grafiği burada durur.
function AskScreen({ pending = null, onRefresh }) {
  const [state, dispatch] = useReducer(askReducer, initialState);
  const [text, setText] = useState("");
  const [examples, setExamples] = useState([]);

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
  }, []);

  const send = (question, choice = null) => {
    const asked = String(question ?? "").trim();
    if (!asked) return;
    dispatch({ type: "ask", question: asked, choice });
    api
      .ask({ question: asked, choice })
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
  useEffect(() => {
    if (pending?.question) send(pending.question);
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
      {state.status === "idle" && <EmptyState examples={examples} onSelect={ask} />}
      {loading && <LoadingSteps />}
      {state.status === "answered" && (
        <>
          <AnswerCard payload={state.payload} onSave={save} />
          {/* ASSUMPTION: AnswerCard grafik yuvasını açmıyor (kendi notu), o yüzden #chart kartın altında. */}
          <ChartView chart={state.payload?.chart} />
        </>
      )}
      {state.status === "clarifying" && (
        <ClarificationCard payload={state.payload} onChoose={choose} onChange={changeQuestion} />
      )}
      {failed && <ErrorCard kind={state.error?.kind} message={state.error?.message} onRebuild={api.rebuild} />}
    </section>
  );
}

// Kural ekranı: liste ile indeksin tazeliği aynı iki istekten gelir; kayıt, silme ve yeniden
// kurma sonrası ekran bunları baştan okur (R5-16).
function RulesFlow() {
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
    />
  );
}

function Screen({ route, pending, onRefresh }) {
  if (route === "rules") return <RulesFlow />;
  return <AskScreen pending={pending} onRefresh={onRefresh} />;
}

export default function App() {
  const [hash, setHash] = useState(currentHash);
  const [health, setHealth] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [saved, setSaved] = useState([]);
  const [history, setHistory] = useState([]);
  const [pending, setPending] = useState(null); // {question, n}: kenar çubuğundan gelen soru
  const route = parseRoute(hash);

  useEffect(() => {
    const onHashChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    let mounted = true;
    fetch(HEALTH_URL)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => mounted && setHealth(data))
      .catch(() => mounted && setHealth(null));
    return () => {
      mounted = false;
    };
  }, []);

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

  // Satıra tıklayınca soru soru ekranında koşar; dar ekranda çekmece kapanır ki cevap görünsün.
  const askFromSidebar = (question) => {
    setPending((current) => ({ question, n: (current?.n ?? 0) + 1 }));
    setSidebarOpen(false);
    if (route !== "ask") window.location.hash = "#/";
  };

  const dot = healthDot(health);
  const chip = chipText(health);

  return (
    <div className="app">
      <header className="masthead">
        <a className="wordmark" href="#/">
          Bilgin
        </a>
        {chip && (
          <span className="chip" title={health?.llm?.url || undefined}>
            {chip}
          </span>
        )}
        <nav className="masthead-nav" aria-label="Bölümler">
          <a className="nav-link" id="nav-ask" href="#/" aria-current={route === "ask" ? "page" : undefined}>
            Sor
          </a>
          <a className="nav-link" id="nav-rules" href="#/kurallar" aria-current={route === "rules" ? "page" : undefined}>
            Kurallar
          </a>
        </nav>
        <span className={`dot dot-${dot.tone}`} role="img" aria-label={dot.tip} title={dot.tip} />
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
          <Sidebar saved={saved} history={history} onAsk={askFromSidebar} onRemoved={refresh} />
        </aside>
        <main id="main">
          <Screen route={route} pending={pending} onRefresh={refresh} />
        </main>
      </div>
    </div>
  );
}
