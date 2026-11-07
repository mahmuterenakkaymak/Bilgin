// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// Soru akışının durumu: her alan bir AskPayload alanıdır, burada zaman/sayaç/tip yok; böylece
// indirgeyici ekrandan bağımsız test edilebilir. Durum adları payload'ınkinden türetilir (R5-2).
export const initialState = {
  status: "idle", // idle | loading | answered | clarifying | failed | network_error
  question: "",
  choice: null,
  payload: null,
  error: null, // {kind, message}; failed ve network_error'da okunur
};

export function askReducer(state = initialState, action = {}) {
  switch (action.type) {
    case "ask":
      return { ...initialState, status: "loading", question: action.question ?? "", choice: action.choice ?? null };
    case "receive": {
      const payload = action.payload ?? null;
      const status = statusOf(payload);
      return {
        ...state,
        status,
        payload,
        question: payload?.question ?? state.question,
        choice: payload?.choice ?? state.choice,
        error: status === "failed" ? errorOf(payload) : null,
      };
    }
    case "fail": {
      // ASSUMPTION: kind "network" kopuk bağlantıdır (ApiError status 0); diğer her şey cevabın kendi hatası.
      const kind = action.kind ?? "failed";
      return {
        ...state,
        status: kind === "network" ? "network_error" : "failed",
        payload: null,
        error: { kind, message: action.message ?? "" },
      };
    }
    case "reset":
      return { ...initialState };
    default:
      return state;
  }
}

function statusOf(payload) {
  if (payload?.status === "answered") return "answered";
  if (payload?.status === "needs_clarification") return "clarifying";
  return "failed";
}

// Cümlenin iki yeri var (error.message ve answer_text); hangisi doluysa o okunur.
function errorOf(payload) {
  const kind = payload?.error?.kind ?? "failed";
  const message = payload?.error?.message || payload?.answer_text || "Cevap üretilemedi.";
  return { kind, message };
}
