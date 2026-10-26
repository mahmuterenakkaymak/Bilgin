// @vitest-environment jsdom
// Akış hem işaret hem olay ister: katlanmış tura tıklamak açıyor, yani durum indirgeyicide
// duruyor. Yapı SSR ile okunur; tıklama gereken iki test jsdom'da gerçekten monte edilir.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import answered from "../fixtures/answered.json";
import { initialState, threadReducer } from "../lib/thread.js";
import Thread from "./Thread.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const noop = () => {};

// R7-5 kanıt satırı: sunucunun `context.line`'ı olduğu gibi okunur, burada kısaltılmaz.
const CONTEXT = {
  uses_turns: [1],
  entities: [{ column: "CARI_KOD", value: "C1" }],
  line: "Önceki cevaptan: müşteri C1 (A)",
};

const CHART = {
  type: "bar",
  option: {
    xAxis: { type: "category", data: ["Siyah Çay 500 g"] },
    yAxis: { type: "value" },
    series: [{ type: "bar", data: [2480] }],
  },
};

// Depodan gelen tur: özet saklandığı kadardır, yük hiç yoktur (Contracts "StoredTurn").
const STORED = {
  n: 1,
  question: "Eylül satışı ne kadar?",
  choice: null,
  status: "answered",
  sql: "SELECT SUM(STHAR_GCMIK) FROM TBLSTHAR",
  answer_text: "Eylül 2026 satışı 8.910 adet.",
  audit_id: "aa1",
  created_at: "2026-10-20T09:00:00+00:00",
  summary: {
    columns: ["SATIS"],
    row_count: 1,
    rows: [[8910]],
    facts: [{ name: "total", display: "8.910" }],
    // Turda grafik vardı; saklanan yalnız türü, yani kartta çizilecek bir option yoktur.
    chart_kind: "bar",
    context: null,
    clarification: null,
  },
};

const CLARIFY = {
  n: 2,
  question: "Bu müşteri kaç sipariş verdi?",
  choice: null,
  status: "needs_clarification",
  sql: null,
  answer_text: "",
  audit_id: "aa2",
  created_at: "2026-10-20T09:01:00+00:00",
  summary: {
    columns: [],
    row_count: 0,
    rows: [],
    facts: [],
    chart_kind: null,
    context: null,
    clarification: { question: "Hangi müşteriyi kastediyorsunuz?", options: ["C1 (A)", "C2 (B)"] },
  },
};

function payload(n, question, extra = {}) {
  return {
    ...answered,
    question,
    turn: n,
    conversation_id: "kon1",
    audit_id: `aa${n}`,
    context: n === 3 ? CONTEXT : null,
    ...extra,
  };
}

function thread(...actions) {
  return actions.reduce((state, action) => threadReducer(state, action), initialState);
}

const THREE = thread(
  { type: "ask", question: "Eylül satışı ne kadar?" },
  { type: "receive", payload: payload(1, "Eylül satışı ne kadar?") },
  { type: "ask", question: "Ya Ağustos?" },
  { type: "receive", payload: payload(2, "Ya Ağustos?") },
  { type: "ask", question: "Bu müşteri kaç sipariş verdi?" },
  { type: "receive", payload: payload(3, "Bu müşteri kaç sipariş verdi?") },
);

const STORED_THREAD = thread(
  { type: "load", conversation: { id: "kon1" }, turns: [STORED] },
  { type: "ask", question: "Ya Ağustos?" },
  { type: "receive", payload: payload(2, "Ya Ağustos?") },
);

// Grafik yalnız markup'ta çizilir: ChartView'ın efekti jsdom'da koşamadığı için `mount` edilen
// akışların yükü graphsız kalır.
const WITH_CHART = thread(
  { type: "load", conversation: { id: "kon1" }, turns: [STORED] },
  { type: "ask", question: "Ya Ağustos?" },
  { type: "receive", payload: payload(2, "Ya Ağustos?", { chart: CHART }) },
);

function markup(state) {
  return renderToStaticMarkup(
    <Thread
      turns={state.turns}
      onExpand={noop}
      onReplay={noop}
      onChoose={noop}
      onChange={noop}
      onSave={noop}
    />,
  );
}

// Bir konuşmanın turları kendi <article> satırında okunur: hangi kartın hangi turda olduğu
// böyle ayrılır, yoksa üçüncü turun kartı birinci turun sanılırdı.
function splitTurns(html) {
  return html.split('<article class="turn">').slice(1);
}

let container;
let root;

// Turların durumu indirgeyicide durur: açma tıklaması yeni durumu yeniden çizer.
function mount(state, handlers = {}) {
  let current = state;
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  const draw = () =>
    root.render(
      <Thread
        turns={current.turns}
        onExpand={(n) => {
          handlers.onExpand?.(n);
          current = threadReducer(current, { type: "expand", n });
          draw();
        }}
        onReplay={handlers.onReplay ?? noop}
        onChoose={handlers.onChoose ?? noop}
        onChange={noop}
        onSave={noop}
      />,
    );
  act(draw);
  return container;
}

function click(node) {
  act(() => node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })));
}

afterEach(() => {
  if (!root) return; // ssr testleri monte edilmez: kapatılacak bir ağaç yoktur
  act(() => root.unmount());
  container.remove();
  root = undefined;
  container = undefined;
});

describe("Thread", () => {
  it("üç turun üçü de akışta: balon ve kart, tam kart yalnız sonuncuda", () => {
    const html = markup(THREE);
    expect(html).toContain('id="thread"');
    const turns = splitTurns(html);
    expect(turns).toHaveLength(3);
    for (const turn of turns) expect(turn).toContain('class="turn-question"');
    expect(html).toContain("Ya Ağustos?");
    expect(html.match(/class="turn-collapsed"/g)).toHaveLength(2);
    expect(splitTurns(html)[0]).not.toContain('id="answer-card"');
    expect(turns[2]).toContain('id="answer-card"');
    expect(turns[2]).toContain('id="evidence-toggle"');
  });

  it("boş akış boş kutudur, çökmez", () => {
    for (const turns of [undefined, null, []]) {
      expect(renderToStaticMarkup(<Thread turns={turns} />)).toContain('id="thread"');
    }
  });

  it("bekleyen tur tam kart değil bekleme kartıdır", () => {
    const html = markup(thread({ type: "ask", question: "Ya Ağustos?" }));
    expect(html).toContain('id="loading"');
    expect(html).toContain("Ya Ağustos?");
    expect(html).not.toContain('id="answer-card"');
    expect(html).not.toContain("✓ Cevaplandı");
  });

  it("netleştirme turu ClarificationCard ile açılır", () => {
    const html = markup(
      thread({ type: "load", conversation: { id: "kon1" }, turns: [STORED, CLARIFY] }),
    );
    const turns = splitTurns(html);
    expect(turns[1]).toContain('id="clarification-card"');
    expect(turns[1]).toContain("Hangi müşteriyi kastediyorsunuz?");
    expect(turns[1]).toContain("C1 (A)");
    expect(turns[1]).not.toContain('id="answer-card"');
  });

  it("kanıt satırı bağlamı olan turun kanıtının üstünde okunur", () => {
    const turns = splitTurns(markup(THREE));
    expect(turns[2]).toContain('id="context-line"');
    expect(turns[2]).toContain("Önceki cevaptan: müşteri C1 (A)");
    expect(turns[0]).not.toContain('id="context-line"');
    expect(turns[1]).not.toContain('id="context-line"');
  });
});

describe("kayıtlı tur", () => {
  it("yeniden çalıştırın notunu ve düğmesini gösterir, grafik kurmaz", () => {
    const turns = splitTurns(markup(WITH_CHART));
    expect(turns[0]).toContain("Eylül 2026 satışı 8.910 adet.");
    expect(turns[0]).toContain('<td class="num">8.910</td>');
    expect(turns[0]).toContain("Tam tablo ve grafik için yeniden çalıştırın.");
    expect(turns[0]).toContain('data-turn-replay="1"');
    expect(turns[0]).toContain("Yeniden çalıştır");
    // Saklanan yalnız grafik türü: çizilecek option olmadığı için kutu da açılmaz.
    expect(turns[0]).not.toContain('id="chart"');
    expect(turns[0]).not.toContain('id="answer-card"');
    expect(turns[1]).toContain('id="chart"');
  });

  it("yeniden çalıştır düğmesi turu açmadan koşar", () => {
    const replays = [];
    const expands = [];
    const app = mount(STORED_THREAD, {
      onReplay: (turn) => replays.push(turn.n),
      onExpand: (n) => expands.push(n),
    });
    click(app.querySelector("[data-turn-replay]"));
    expect(replays).toEqual([1]);
    expect(expands).toEqual([]);
  });
});

describe("aç/kapat", () => {
  it("katlanmış tura tıklayınca tur kendi tam kartını gösterir", () => {
    const app = mount(THREE);
    const first = app.querySelectorAll(".turn")[0];
    expect(first.querySelector(".turn-collapsed")).not.toBeNull();
    expect(first.querySelector("#answer-card")).toBeNull();

    click(first.querySelector(".turn-collapsed"));

    expect(app.querySelectorAll(".turn")[0].querySelector("#answer-card")).not.toBeNull();
    // Başka turların kartı yerinde: açma yalnız o turun katını çevirir.
    expect(app.querySelectorAll(".turn")[2].querySelector("#answer-card")).not.toBeNull();
  });

  it("klavyeyle de açılır", () => {
    const expands = [];
    const app = mount(THREE, { onExpand: (n) => expands.push(n) });
    const collapsed = app.querySelectorAll(".turn")[0].querySelector(".turn-collapsed");
    act(() =>
      collapsed.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true })),
    );
    expect(expands).toEqual([1]);
  });
});
