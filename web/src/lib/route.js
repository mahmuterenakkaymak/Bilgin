// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

const ROUTES = { "/kurallar": "rules" };

// ASSUMPTION: "#kurallar" (slash atlanırsa) da kural ekranıdır; tanınmayan her hash soru ekranına düşer.
export function parseRoute(hash) {
  const path = String(hash ?? "")
    .trim()
    .replace(/^#/, "")
    .replace(/\/+$/, "")
    .toLowerCase();
  if (path === "" || path === "/") return "ask";
  return ROUTES[path.startsWith("/") ? path : `/${path}`] ?? "ask";
}
