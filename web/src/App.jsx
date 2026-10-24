import { useEffect, useReducer, useState } from "react";
import AnswerCard from "./components/AnswerCard.jsx";
import AskBox from "./components/AskBox.jsx";
import EmptyState from "./components/EmptyState.jsx";
import ErrorCard from "./components/ErrorCard.jsx";
import LoadingSteps from "./components/LoadingSteps.jsx";
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

// Soru ekranı: akışın halleri burada birbirine bağlanır (R5-18). Netleştirme kartı sonraki
// görevin; burada boş, bekleyen, cevap ve hata yuvaları durur.
function AskScreen() {
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
      );
  };

  // Çip soruyu kutuya yazar ve bekletmeden sorar (R5-18).
  const ask = (question) => {
    setText(question ?? "");
    send(question);
  };

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
      {state.status === "answered" && <AnswerCard payload={state.payload} />}
      {failed && <ErrorCard kind={state.error?.kind} message={state.error?.message} onRebuild={api.rebuild} />}
    </section>
  );
}

function Screen({ route }) {
  if (route === "rules") {
    return (
      <section className="screen">
        <h1 className="screen-title">İş kuralları</h1>
        <p className="screen-lead">Kurallar, Bilgin'in bir soruda hangi terimi ne anladığını belirler.</p>
      </section>
    );
  }
  return <AskScreen />;
}

export default function App() {
  const [hash, setHash] = useState(currentHash);
  const [health, setHealth] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
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
        <aside id="sidebar" className={sidebarOpen ? "sidebar is-open" : "sidebar"} aria-label="Kayıtlılar ve geçmiş" />
        <main id="main">
          <Screen route={route} />
        </main>
      </div>
    </div>
  );
}
