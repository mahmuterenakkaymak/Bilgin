import { useEffect, useReducer, useRef, useState } from "react";
import AnswerCard from "./components/AnswerCard.jsx";
import AskBox from "./components/AskBox.jsx";
import ClarificationCard from "./components/ClarificationCard.jsx";
import { ConnectionsFlow } from "./components/ConnectionsScreen.jsx";
import { DbBanner, DbDot } from "./components/DbStatus.jsx";
import EmptyState from "./components/EmptyState.jsx";
import ErrorCard from "./components/ErrorCard.jsx";
import LangToggle from "./components/LangToggle.jsx";
import LoadingSteps from "./components/LoadingSteps.jsx";
import { MapFlow } from "./components/MapScreen.jsx";
import MastheadNav from "./components/MastheadNav.jsx";
import ReadyQuestionsScreen from "./components/ReadyQuestionsScreen.jsx";
import RulesScreen from "./components/RulesScreen.jsx";
import Sidebar from "./components/Sidebar.jsx";
import StartScreen from "./components/StartScreen.jsx";
import Thread from "./components/Thread.jsx";
import UsersScreen from "./components/UsersScreen.jsx";
import { makeT, useT } from "./i18n/index.js";
import * as api from "./lib/api.js";
import { canSee } from "./lib/auth.js";
import { parseRoute } from "./lib/route.js";
import { applyTheme, nextTheme, readStored, store } from "./lib/theme.js";
import { initialState as initialThread, threadReducer } from "./lib/thread.js";

// Düğmenin gördüğü ad, sıradaki temayı değil seçili olanı söyler: "Koyu" yazan bir düğmeye
// basınca ne olacağı belirsiz kalmasın.
const HEALTH_URL = "/api/health";
const THEME_KEYS = { system: "theme.system", dark: "theme.dark", light: "theme.light" };
// Çipteki rollerin anahtarları: `lib/auth.js` ve `lib/startCards.js` Türkçe sabitlerini kendi
// ekranları için taşıyor; başlık katalogdan okur, tanınmayan kod kendi adıyla kalır.
const ROLE_KEYS = { admin: "role.admin", user: "role.user" };
const BUSINESS_ROLE_KEYS = {
  satis: "role.satis",
  satin_alma: "role.satin_alma",
  muhasebe: "role.muhasebe",
  yonetim: "role.yonetim",
  genel: "role.genel",
};

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
export function healthDot(health, lang = "tr") {
  const t = makeT(lang);
  if (!health) {
    return { tone: "unknown", label: t("health.unknown"), tip: t("health.tip.unknown") };
  }
  if (health.llm && health.llm.reachable === false) {
    const reason = health.llm.reason;
    return {
      tone: "down",
      label: t("health.down"),
      tip: reason ? t("health.tip.downReason", { reason }) : t("health.tip.down"),
    };
  }
  if (health.index && health.index.fresh === false) {
    const reason = health.index.reason;
    return {
      tone: "stale",
      label: t("health.stale"),
      tip: reason ? t("health.tip.staleReason", { reason }) : t("health.tip.stale"),
    };
  }
  return { tone: "ok", label: t("health.ok"), tip: t("health.tip.ok") };
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
// İş rolü (R7-16) Run 7 öncesi kimlikte yoktur; halka yoksa çip onu hiç taşımaz, boş bırakmaz.
function userLabel(user, t) {
  const code = user?.business_role;
  const business = code ? (BUSINESS_ROLE_KEYS[code] ? t(BUSINESS_ROLE_KEYS[code]) : code) : "";
  const role = ROLE_KEYS[user?.role];
  return [user?.username, business, role ? t(role) : ""].filter(Boolean).join(" · ");
}

// Konuşmanın satırı en son sorulan soruyla adlanır (M26 review 4): /api/conversations'ın başlığı ilk
// sorundur ve sözleşme öyle diyor; en son sorulanı GEÇMİŞ satırları biliyor — aynı sorunun iki yüzü.
// Kayıtlar en yeni önce gelir, o yüzden ilk görülen en sondur. ASSUMPTION: geçmiş listesi HISTORY_N
// ile sınırlı; dışına düşen konuşma satırı ilk sorusuyla kalır.
function lastQuestions(history) {
  const latest = new Map();
  for (const row of Array.isArray(history) ? history : []) {
    const id = typeof row?.conversation_id === "string" ? row.conversation_id : "";
    const question = String(row?.question ?? "").trim();
    if (id && question && !latest.has(id)) latest.set(id, question);
  }
  return latest;
}

// Soru ekranı: akışın halleri burada birbirine bağlanır (R5-18). Boş, bekleyen, cevap,
// netleştirme ve hata yuvaları burada durur; cevabın grafiği kartın içindedir.
// Boş ekran (R7-21): henüz soru yokken ekran panodur — StartScreen kartları, soru kutusunu ve
// örnek çipleri birlikte getirir; ilk soruyla bu ekran akışın kendisine bırakır.
// Konuşma (R7-15): turlar `lib/thread.js` indirgeyicisinde durur. İlk soru konuşmayı henüz
// açmadığı için bugünkü gibi kutunun altında tek karttır; cevap geldiği an adres #/c/<id> olur ve
// aynı turlar akışa taşınır — soru kutusu son turun altına iner.
function AskScreen({
  pending = null,
  onRefresh,
  onRebuild,
  onNote = null,
  conversation = null,
  datasetKey = 0,
  canEditRules = false,
  datasetName = "",
  isAdmin = false,
  resetToken = 0,
}) {
  const { t } = useT();
  const [state, dispatch] = useReducer(threadReducer, initialThread);
  const [text, setText] = useState("");
  const [examples, setExamples] = useState([]);
  const [rulesEmpty, setRulesEmpty] = useState(false);
  // Kartları okunamayan kümenin anahtarı (R7-21): o küme eski boş ekranla devam eder. Anahtar
  // küme numarası olduğu için geçici bir ağ hatası kalıcı bir "pano yok" durumuna dönmez —
  // küme değişince ekran kendiliğinden yeniden dener.
  const [startBroken, setStartBroken] = useState(-1);
  // Kartın "SQL'i yeniden onayla"sı (R7-21): hangi kartın düzeltildiği, cevabın hangi kartı
  // güncelleyeceğini söyler. Başka bir soru koşulursa bağlantı düşer — ilgisiz bir cevap eski
  // kartın güncelleyicisi olamaz.
  const [reapproving, setReapproving] = useState(null); // {id, question} | null

  // Akışın son turu: konuşma açılmamışsa tek cevap kartı, açılmışsa akışın en alt satırı odur.
  const turns = state.turns;
  const last = turns.length > 0 ? turns[turns.length - 1] : null;
  const loading = Boolean(last?.pending);

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

  // Adresin okuduğu konuşma: açmak hiçbir SQL koşturmaz, GET yalnız depoda yazılı olanı getirir
  // (R7-8). Yaşayan konuşmanın adresi ilk cevapla yazıldığı için `opened` orada da dolu olur ve
  // akış baştan okunmaz; adres değişmeden aynı adrese dönmek de okuma yenilemez.
  const opened = useRef(null);
  useEffect(() => {
    if (!conversation) {
      opened.current = null;
      return undefined;
    }
    if (opened.current === conversation) return undefined;
    opened.current = conversation;
    let mounted = true;
    onNote?.("");
    api
      .conversationGet(conversation)
      .then((data) =>
        mounted &&
        dispatch({ type: "load", conversation: data?.conversation, turns: data?.turns }),
      )
      .catch((error) => {
        if (!mounted) return;
        // Olmayan konuşma ile erişilemeyen konuşma aynı yere düşer: cümle ve kök adres.
        // `ask.noConversation` sunucudaki 404 ile aynı sözcükleri taşır (conversations_api).
        onNote?.(
          error?.status === 404 ? t("ask.noConversation") : error?.message || t("ask.conversationFailed"),
        );
        window.location.hash = "#/";
      });
    return () => {
      mounted = false;
    };
  }, [conversation]);

  // auditId verilirse soru modele baştan sorulmaz: geçmişteki SQL yeniden çalışır (/api/replay).
  // Açık bir konuşma varsa soru ona bir tur ekler; kimlik her soruyla gider (R7-15).
  const send = (question, choice = null, auditId = null, conversationId = state.conversationId) => {
    const asked = String(question ?? "").trim();
    if (!asked) return;
    if (reapproving && reapproving.question !== asked) setReapproving(null);
    dispatch({ type: "ask", question: asked, choice });
    (auditId ? api.replay(auditId) : api.ask({ question: asked, choice, conversation_id: conversationId }))
      .then((payload) => {
        dispatch({ type: "receive", payload });
        // Cevapla biten tur kutuyu boşaltır: kutu akışın üstündeki balonun kopyasını taşırsa
        // takip eden soru seç-sil ile başlar ve telefonda "Sorunuzu yazın" ipucu hiç görünmez.
        // Netleştirme ve hata soruyu tutar — "Soruyu değiştir" kutudaki metni düzenler. Kutuda o
        // soru duruyorsa silinir: şıkla koşan cevabın altına yazılan taslak kaybolmasın.
        if (payload?.status === "answered" && !payload?.clarification) {
          setText((current) => (current.trim() === asked ? "" : current));
        }
        // İlk cevap konuşmayı sunucuda açtı: adres turların kimliğidir, yenileme akışı geri
        // getirir. Turlar zaten elde; adresin açacağı okuma aynı konuşmadır, o yüzden geçilir.
        if (payload?.conversation_id && payload.conversation_id !== conversation) {
          opened.current = payload.conversation_id;
          window.location.hash = `#/c/${payload.conversation_id}`;
        }
      })
      .catch((error) => dispatch({ type: "fail", message: error?.message ?? "" }))
      // Soru neyle biterse bitsin günlüğe bir satır düşer: kenar çubuğu her durumda tazelenir.
      .finally(() => onRefresh?.());
  };

  // Kayıtlı turun "Yeniden çalıştır"ı (R7-15, M23 review 1): soru modele baştan sorulmaz, kayıtlı
  // SQL /api/replay'den geçer. Yeni tur açılmaz - cevap koşumun ait olduğu tura yerleşir: sunucu bu
  // koşumu konuşmaya yazmadığı için eklenen bir tur sıradaki sorunun numarasını çalardı. Ne bir
  // konuşma kimliği gönderilir ne de yükten kimlik benimsenir; adres olduğu gibi kalır.
  const replay = (turn) => {
    if (!turn?.audit_id) return;
    dispatch({ type: "replay", n: turn.n });
    api
      .replay(turn.audit_id)
      .then((payload) => dispatch({ type: "receive", payload }))
      .catch((error) => dispatch({ type: "fail", message: error?.message ?? "" }))
      .finally(() => onRefresh?.());
  };

  // Kenar çubuğundan gelen soru, kutudan sorulmuş gibi koşar; sayaç aynı sorunun ikinci
  // tıklayışını da yeni bir istek yapar.
  // Soru kutuya da yazılır ve ekran kutuya kayar: yoksa kutuda eski metin kalır, bekleme adımları
  // ve cevap ekranın altında açılır, tıklama hiçbir şey yapmamış gibi görünür (2026-10-25).
  // Kenar çubuğunun sorusu kendi başına bir sorudur: açık bir konuşma varsa yenisi açılır.
  useEffect(() => {
    if (!pending?.question) return;
    dispatch({ type: "reset" });
    setText(pending.question);
    send(pending.question, null, pending.auditId ?? null, null);
    document.getElementById("main")?.scrollIntoView?.({ block: "start", behavior: "smooth" });
  }, [pending]);

  // Çip soruyu kutuya yazar ve bekletmeden sorar (R5-18).
  const ask = (question) => {
    setText(question ?? "");
    send(question);
  };

  // Seçenek, sorunun hangi anlamla koşulacağını sabitler: aynı soru choice ile yeniden koşar (R5-11).
  // Akışta netleştirme sorusu son turdur; indirgeyici şıkkı onun üstünü tamamlayarak koşar.
  const choose = (option) => send(last?.question ?? "", option);

  // "Soruyu değiştir" kartı kapatmaz: imleç kutuya döner, kullanıcı yazıp yeniden sorar.
  const changeQuestion = () => document.getElementById("question")?.focus();

  // Kartın SQL'i yürümediyse yönetici soruyu kutuya alır (R7-21): yeniden koşan cevabın SQL'i
  // hazır soruya yeniden onaylanır, yani hata kartı düzeltmenin yolunu gösterir. Kartın kimliği de
  // akışta kalır ki cevap geldiğinde düğme "Bu SQL ile güncelle" olarak okunsun.
  const reapprove = (card) => {
    setReapproving({ id: card?.id ?? null, question: String(card?.question ?? "").trim() });
    setText(card?.question ?? "");
    changeQuestion();
  };

  // Kayıt kenar çubuğunun listesine de düşer.
  const save = (item) =>
    api.savedAdd(item).then((result) => {
      onRefresh?.();
      return result;
    });

  // Yeni konuşma: akış boşalır ve adres köke döner; turlar sunucuda durmaya devam eder.
  const newConversation = () => {
    dispatch({ type: "reset" });
    onNote?.("");
    setReapproving(null);
    setText("");
    window.location.hash = "#/";
    document.getElementById("question")?.focus();
  };

  // Silinen konuşma (M23 review 2): kenar çubuğu açık konuşmayı silince App `resetToken`ı büyütür;
  // ekran "Yeni konuşma"nın yaptığı gibi boşalır. Başka bir konuşmanın silinmesi sayacı büyütmez,
  // o yüzden ekranda hiçbir şey değişmez. İlk kurulum sayacı değiştirmez, yani açılış boşaltmaz.
  const seenReset = useRef(resetToken);
  useEffect(() => {
    if (seenReset.current === resetToken) return;
    seenReset.current = resetToken;
    newConversation();
  }, [resetToken]);

  // Konuşma açıkken ekran akıştır: turlar yukarıdan aşağı sıralanır, soru kutusu en alttaki
  // turun altına iner (R7-15). Kartın hali TurnCard'da çözülür.
  if (conversation) {
    return (
      <section className="screen ask-flow">
        <button type="button" id="new-conversation" className="btn btn-ghost" onClick={newConversation}>
          {t("ask.newConversation")}
        </button>
        <Thread
          turns={turns}
          onExpand={(n) => dispatch({ type: "expand", n })}
          onReplay={replay}
          onChoose={choose}
          onChange={changeQuestion}
          onSave={save}
          isAdmin={isAdmin}
          reapproveId={reapproving?.id ?? null}
        />
        <AskBox value={text} onChange={setText} onAsk={ask} loading={loading} examples={examples} />
      </section>
    );
  }

  // Panonun ekranı (R7-21): kartların altında soru kutusu ve örnek çipler. Henüz soru yokken ve
  // kartlar okunabilmişken ekran odur; okunamadıysa aşağıdaki boş ekran aynı küme için sürer.
  if (turns.length === 0 && startBroken !== datasetKey) {
    return (
      <StartScreen
        examples={examples}
        text={text}
        onChange={setText}
        onAsk={ask}
        onReapprove={reapprove}
        onFailed={() => setStartBroken(datasetKey)}
        isAdmin={isAdmin}
        loading={loading}
        datasetKey={datasetKey}
      />
    );
  }

  return (
    <section className="screen ask-flow">
      <AskBox
        value={text}
        onChange={setText}
        onAsk={ask}
        loading={loading}
        examples={turns.length === 0 ? [] : examples}
      />
      {turns.length === 0 && (
        <EmptyState
          examples={examples}
          rulesHint={canEditRules && rulesEmpty}
          datasetName={datasetName}
          onSelect={ask}
        />
      )}
      {loading && <LoadingSteps />}
      {last &&
        !last.pending &&
        (last.summary?.clarification ? (
          <ClarificationCard
            payload={last.payload ?? { clarification: last.summary.clarification }}
            onChoose={choose}
            onChange={changeQuestion}
          />
        ) : last.status === "answered" && last.payload ? (
          <AnswerCard
            payload={last.payload}
            choice={last.choice}
            onSave={save}
            isAdmin={isAdmin}
            reapproveId={reapproving?.id ?? null}
          />
        ) : (
          <ErrorCard kind={last.payload?.error?.kind} message={last.answer_text} onRebuild={onRebuild} />
        ))}
    </section>
  );
}

// Kural ekranı: liste ile indeksin tazeliği aynı iki istekten gelir; kayıt, silme ve yeniden
// kurma sonrası ekran bunları baştan okur (R5-16).
function RulesFlow({ onChanged, readOnly }) {
  const { t } = useT();
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
      .catch((failure) => setError(failure?.message || t("rules.loadFailed")));
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
  const { t } = useT();
  const [users, setUsers] = useState(null); // null: henüz okunmadı
  const [error, setError] = useState("");

  const refresh = () => {
    api
      .usersList()
      .then((payload) => setUsers(Array.isArray(payload?.users) ? payload.users : []))
      .catch((failure) => setError(failure?.message || t("users.loadFailed")));
  };

  useEffect(refresh, []);

  // `currentUser` oturum sahibinin kendisi: kendi satırındaki düğmeler buna göre ayıklanır.
  return (
    <UsersScreen users={users ?? []} currentUser={currentUser} loading={!users} error={error} onRefresh={refresh} />
  );
}

// Hazır soru defteri (R7-21): kümenin bütün satırları tek istekten okunur; onay, düzenleme ve
// silme sonrası aynı istek yinelenir, böylece liste sunucudaki halini gösterir.
function ReadyFlow() {
  const { t } = useT();
  const [rows, setRows] = useState(null); // null: henüz okunmadı
  const [error, setError] = useState("");

  const refresh = () => {
    api
      .readyList()
      .then((payload) =>
        setRows(Array.isArray(payload?.ready_questions) ? payload.ready_questions : []),
      )
      .catch((failure) => setError(failure?.message || t("ready.loadFailed")));
  };

  useEffect(refresh, []);

  return <ReadyQuestionsScreen rows={rows ?? []} loading={!rows} error={error} onRefresh={refresh} />;
}

function Screen({
  route,
  conversation,
  pending,
  onRefresh,
  onChanged,
  onRebuild,
  onSwitched,
  onNote,
  datasetKey,
  datasetName,
  readOnly,
  currentUser,
  resetToken,
}) {
  if (route === "rules") return <RulesFlow onChanged={onChanged} readOnly={readOnly} />;
  if (route === "users") return <UsersFlow currentUser={currentUser} />;
  if (route === "ready") return <ReadyFlow />;
  if (route === "connections") return <ConnectionsFlow />;
  if (route === "map") return <MapFlow onSwitched={onSwitched} />;
  return (
    <AskScreen
      pending={pending}
      conversation={conversation}
      onRefresh={onRefresh}
      onRebuild={onRebuild}
      onNote={onNote}
      datasetKey={datasetKey}
      datasetName={datasetName}
      canEditRules={!readOnly}
      isAdmin={!readOnly}
      resetToken={resetToken}
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
  const [conversations, setConversations] = useState([]);
  // Silinen açık konuşma (M23 review 2): her artış soru ekranını "Yeni konuşma" gibi boşaltır.
  const [resetToken, setResetToken] = useState(0);
  const [pending, setPending] = useState(null); // {question, n}: kenar çubuğundan gelen soru
  const [datasetKey, setDatasetKey] = useState(0); // her küme değişiminde büyür, örnekler tazelenir
  const [theme, setTheme] = useState(() => readStored(themeStorage()));
  // Cümlenin iki kaynağı var: kapınınki (prop) ve konuşmanın açılamaması. İkincisi burada durur,
  // çünkü onu yalnız soru ekranının akışı üretir.
  const [localNote, setLocalNote] = useState("");
  const { t, lang, setLang } = useT();
  // Adres ya bir ekrandır ya bir konuşma (`#/c/<id>`, R7-15); konuşmanın ekranı soru ekranıdır.
  // Rol kararı kapının girişiyle aynı: `#/kullanicilar` ile açan ya da yenileyen sıradan bir
  // kullanıcı yönetici defterini görmez, soru ekranına bir cümleyle düşer. Kullanıcı yoksa kabuk
  // tek kullanıcılıdır ve Run 5'teki gibi her ekran açıktır.
  const requested = parseRoute(hash);
  const conversation = requested?.route === "conversation" ? requested.id : null;
  const requestedRoute = conversation ? "conversation" : requested;
  const allowed = !user || canSee(requestedRoute, user.role);
  const route = allowed ? requestedRoute : "ask";
  const screenNote = localNote || note || (allowed ? "" : t("auth.notAllowed"));

  // Kök nitelik seçili temayı taşısın: açılışta bir kez, her değişimde yeniden. main.jsx ilk
  // boyamadan önce aynı işi yaptığı için koyu teması olan açılışta açık bir kare görmez.
  useEffect(() => applyTheme(document, theme), [theme]);

  // Kişinin kayıtlı dili açılış ya da girişle öğrenilir: main.jsx onu `me` gelmeden önce
  // çözemediği için sıra burada tamamlanır (R8-15: me.lang > yerel tercih > tarayıcı).
  useEffect(() => {
    if (user?.lang) setLang(user.lang);
  }, [user?.lang]);

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
    api
      .conversationsList()
      .then((data) => setConversations(Array.isArray(data?.conversations) ? data.conversations : []))
      .catch(() => {});
  };

  useEffect(() => {
    refresh();
  }, []);

  // Kenar çubuğundan bir konuşma silindi (M23 review 2): silinen açık konuşmaysa ekran "Yeni
  // konuşma" gibi boşanır; aksi hâlde (ya da kayıttan silmede, ki id gelmez) yalnız liste tazelenir.
  const removed = (id) => {
    if (id && id === conversation) setResetToken((token) => token + 1);
    refresh();
  };

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

  // KONUŞMALAR satırları en son sorulan soruyla adlanır: listeye kendi sözleşmesinde olmayan alanı
  // burada GEÇMİŞ'in en yeni kaydı ekliyor. Sonraki satır aynı listeyi okur, iki yüz ayrılmaz.
  const asked = lastQuestions(history);
  const sidebarConversations = conversations.map((item) =>
    asked.has(item?.id) ? { ...item, last_question: asked.get(item.id) } : item,
  );

  const dot = healthDot(health, lang);
  const chip = chipParts(health);
  const who = userLabel(user, t);
  const themeLabel = t(THEME_KEYS[theme]);

  return (
    <div className="app">
      <header className="masthead">
        <a className="wordmark" href="#/">
          {t("root.brand")}
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
        {/* Konuşma soru ekranının bir halidir: gezinmede "Sor" açık kalır. */}
        <MastheadNav route={conversation ? "ask" : route} user={user} />
        <button
          type="button"
          id="theme-toggle"
          className="btn btn-theme"
          aria-label={t("theme.toggle", { label: themeLabel })}
          onClick={cycleTheme}
        >
          {themeLabel}
        </button>
        {/* Dil de tema gibi görünümün kendisidir: cevabı değil, arayüzü çevirir. */}
        <LangToggle user={user} />
        {/* Sözcük noktanın yanında: ipucu kümenin tamamına, adlandırma noktaya ait kalır. */}
        <span className="health" title={dot.tip}>
          <span className={`dot dot-${dot.tone}`} role="img" aria-label={dot.tip} />
          <span id="health-label">{dot.label}</span>
        </span>
        {/* Veritabanının sağlığı modelden ayrı bir gerçek (R7-27): nokta arka plan yoklamasının
            son cevabını gösterir, başlık bu yüzden hiçbir `SELECT 1` beklemez; küme SQLite ise
            nötr kalır. */}
        {user && <DbDot db={health?.db} isAdmin={user.role === "admin"} />}
        {who && (
          <span className="chip" id="user-chip" title={t("shell.userChip")}>
            {who}
          </span>
        )}
        {onLogout && (
          <button type="button" id="logout" className="btn btn-ghost" onClick={logout}>
            {t("shell.logout")}
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
          {t("shell.sidebarToggle")}
        </button>
        <aside
          id="sidebar"
          className={sidebarOpen ? "sidebar is-open" : "sidebar"}
          aria-label={t("shell.sidebarToggle")}
        >
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
              {t("shell.sidebarClose")}
            </button>
          )}
          <Sidebar
            saved={saved}
            history={history}
            conversations={sidebarConversations}
            onAsk={askFromSidebar}
            onRemoved={removed}
          />
        </aside>
        <main id="main">
          {/* Cümle düşülen ekranın üstünde durur; başka bir ekrana geçince kendiliğinden kalkar. */}
          {screenNote && route === "ask" && (
            <p className="route-note" id="route-note">
              {screenNote}
            </p>
          )}
          {/* Düşmüş veritabanının bandı sorunun tam üstünde durur (R7-27): panonun, akışın ve
              konuşmanın ekranları aynı üç haldir. Kutuyu örtmez — soru koşmaz, yazılmaz da değil. */}
          {(route === "ask" || route === "conversation") && (
            <DbBanner db={health?.db} isAdmin={!user || user.role === "admin"} />
          )}
          <Screen
            route={route}
            conversation={conversation}
            pending={pending}
            onNote={setLocalNote}
            onRefresh={refresh}
            onChanged={refreshHealth}
            onRebuild={() => api.rebuild().then(refreshHealth)}
            onSwitched={switched}
            datasetKey={datasetKey}
            datasetName={health?.dataset?.display_name ?? ""}
            readOnly={Boolean(user && user.role !== "admin")}
            currentUser={user}
            resetToken={resetToken}
          />
        </main>
      </div>
    </div>
  );
}
