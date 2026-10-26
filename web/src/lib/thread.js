// Konuşmanın akışı (PLAN R7-15): kayıtlı turlar, yolda olan soru ve cevabın kendi turuna yerleşmesi.
// Tur alanları sunucunun adlarıdır (answer_text, summary, audit_id); indirgeyici yalnız kendi
// anahtarlarını ekler: stored, pending, expanded, collapsed. Böylece kart hem kaydı hem canlı yükü
// aynı adlarla okur.

// Kayıtlı turun özeti ile canlı yükün alanları aynı kaba akar; ikisi de yoksa boş sonuç okunur.
const EMPTY_SUMMARY = {
  columns: [],
  row_count: 0,
  rows: [],
  facts: [],
  chart_kind: null,
  context: null,
  clarification: null,
};

export const initialState = { conversationId: null, turns: [] };

export function threadReducer(state = initialState, action = {}) {
  switch (action.type) {
    case "load":
      // GET /api/conversations/{id} -> {conversation, turns}; açmak hiçbir SQL koşturmaz.
      return mark({
        conversationId: action.conversation?.id ?? null,
        turns: (Array.isArray(action.turns) ? action.turns : []).map(storedTurn),
      });
    case "ask": {
      const turns = [...state.turns];
      const last = turns.at(-1);
      // Seçilen şık bekleyen netleştirme turunu tamamlar (R7-7): numarası aynı kalır, tur üstüne
      // yenisi eklenmez.
      const index = action.choice && last?.status === "needs_clarification" && last.question === action.question
        ? turns.length - 1
        : -1;
      const turn = {
        n: index >= 0 ? last.n : (last?.n ?? 0) + 1,
        question: action.question ?? "",
        choice: action.choice ?? null,
        status: "loading",
        answer_text: "",
        sql: null,
        audit_id: null,
        summary: { ...EMPTY_SUMMARY },
        payload: null,
        stored: false,
        pending: true,
        expanded: index >= 0 ? last.expanded : false,
      };
      if (index >= 0) turns[index] = { ...last, ...turn };
      else turns.push(turn);
      return mark({ ...state, turns });
    }
    case "receive": {
      const index = state.turns.findIndex((turn) => turn.pending);
      if (index < 0) return state; // gecikmiş yanıt: yerini kaybettiği listeye dokunmaz
      const payload = action.payload ?? null;
      const turns = [...state.turns];
      turns[index] = {
        ...turns[index],
        n: payload?.turn ?? turns[index].n,
        question: payload?.question ?? turns[index].question,
        // Yük seçimi boş bıraksa da soru o seçimle koşmuştur; şık turda kalmalı.
        choice: payload?.choice ?? turns[index].choice,
        status: payload?.status ?? "failed",
        answer_text: payload?.answer_text || payload?.error?.message || "",
        sql: payload?.sql ?? null,
        audit_id: payload?.audit_id ?? null,
        summary: summaryOf(payload),
        payload,
        pending: false,
      };
      // İlk soru konuşmayı sunucuda açar: kimlik sonraki sorunun ve adresin kaynağıdır.
      return mark({ conversationId: payload?.conversation_id ?? state.conversationId, turns });
    }
    case "fail": {
      const index = state.turns.findIndex((turn) => turn.pending);
      if (index < 0) return state;
      const turns = [...state.turns];
      turns[index] = {
        ...turns[index],
        status: "failed",
        answer_text: action.message || "Cevap üretilemedi.",
        pending: false,
      };
      return mark({ ...state, turns });
    }
    case "expand":
      return mark({
        ...state,
        turns: state.turns.map((turn) => (turn.n === action.n ? { ...turn, expanded: !turn.expanded } : turn)),
      });
    case "reset":
      return { ...initialState };
    default:
      return state;
  }
}

// Katlanma listeye göre belirlenir: son tur hiç katlanmaz, eskiler yalnızca kullanıcının
// açtığı kadar açık kalır. Yeni bir tur eklenince önceki son tur kendiliğinden katlanır.
function mark(state) {
  const last = state.turns.length - 1;
  return {
    ...state,
    turns: state.turns.map((turn, i) => ({ ...turn, collapsed: i < last && !turn.expanded })),
  };
}

// Kayıtlı tur (Contracts "StoredTurn"): özet depoda ne kadar saklandıysa o, tam kart için yük yoktur.
function storedTurn(item) {
  return {
    n: item?.n,
    question: item?.question ?? "",
    choice: item?.choice ?? null,
    status: item?.status ?? "failed",
    answer_text: item?.answer_text ?? "",
    sql: item?.sql ?? null,
    audit_id: item?.audit_id ?? null,
    summary: summaryOf(item?.summary),
    payload: null,
    stored: true,
    pending: false,
    expanded: false,
  };
}

function summaryOf(source) {
  if (!source) return { ...EMPTY_SUMMARY };
  const rows = Array.isArray(source.rows) ? source.rows : [];
  return {
    columns: Array.isArray(source.columns) ? source.columns : [],
    row_count: Number.isFinite(source.row_count) ? source.row_count : rows.length,
    rows,
    facts: Array.isArray(source.facts) ? source.facts : [],
    chart_kind: source.chart_kind ?? source.chart?.kind ?? null,
    context: source.context ?? null,
    clarification: source.clarification ?? null,
  };
}
