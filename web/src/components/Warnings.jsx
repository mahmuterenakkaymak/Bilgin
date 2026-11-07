// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// Uyarılar: cevabın altındaki kehribar bant. Her uyarı kendi satırıdır; mesajı Python üretir
// (engine/checks.py), burada yalnız okunur — boş liste bantı hiç kurmaz (R5-18).
export default function Warnings({ warnings = [] }) {
  const items = (Array.isArray(warnings) ? warnings : []).filter((warning) => warning?.message);
  if (!items.length) return null;

  return (
    <div id="warnings" className="warnings" role="status">
      {items.map((warning, index) => (
        <p className="warning" key={`${index}-${warning.code ?? ""}`}>
          <span className="warning-mark" aria-hidden="true">
            ⚠
          </span>
          <span>{warning.message}</span>
        </p>
      ))}
    </div>
  );
}
