// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { useState } from "react";
import { formatCell, formatNumber, formatSeconds } from "../lib/format.js";

// "Nasıl hesapladım": cevabın dayanakları — SQL, kullanılan tablolar ve kurallar, maskeler,
// olgular, araç adımları, denetim kaydı ve süreler (R5-18). Gövde hep kurulur, kapanışta
// `hidden` kalır; böylece tarayıcıda bulunabilir kalır ve hiçbir alan akışta kaybolmaz.
const TIMINGS = [
  { key: "agent_s", label: "ajan", unit: "s" },
  { key: "execute_ms", label: "sorgu", unit: "ms" },
  { key: "narrate_s", label: "anlatı", unit: "s" },
  { key: "total_s", label: "toplam", unit: "s" },
];

function join(items) {
  const values = (Array.isArray(items) ? items : []).map((item) => String(item ?? "").trim()).filter(Boolean);
  return values.length ? values.join(", ") : "–";
}

// Süreler koşmayan aşamaları hiç yazmaz: 0, "koşmadı" demektir. Saniyenin tek ondalık basamağı
// 0,04'ü "0,0 sn" yapar — okunur bir süre olmadığı için o da yazılmaz.
function timingsText(timings) {
  const parts = [];
  for (const { key, label, unit } of TIMINGS) {
    const value = timings?.[key];
    if (typeof value !== "number" || !Number.isFinite(value)) continue;
    if (value < (unit === "ms" ? 0 : 0.05)) continue;
    parts.push(unit === "ms" ? `${label} ${formatNumber(value)} ms` : `${label} ${formatSeconds(value)}`);
  }
  return parts.join(" · ");
}

export default function Evidence({ payload }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const sql = typeof payload?.sql === "string" ? payload.sql : "";
  const timings = timingsText(payload?.timings);
  const facts = (Array.isArray(payload?.facts) ? payload.facts : []).filter((fact) => fact?.label);
  const steps = (Array.isArray(payload?.steps) ? payload.steps : []).filter(
    (step) => step && (step.tool || step.summary),
  );
  const notes = (Array.isArray(payload?.notes) ? payload.notes : []).filter((note) => String(note ?? "").trim());

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
    } catch {
      setCopied(false); // panoya kopyalanamayan tarayıcıda düğme "Kopyala"da kalır
    }
  };

  return (
    <div className="evidence">
      <button
        type="button"
        id="evidence-toggle"
        className="evidence-toggle"
        aria-expanded={open}
        aria-controls="evidence"
        onClick={() => setOpen((value) => !value)}
      >
        <span className="evidence-caret" aria-hidden="true">
          {open ? "▾" : "▸"}
        </span>
        Nasıl hesapladım
      </button>
      <div id="evidence" className="evidence-body" hidden={!open}>
        <div className="evidence-sql">
          <pre className="sql-block">
            <code>{sql || "–"}</code>
          </pre>
          <button type="button" id="copy-sql" className="btn btn-ghost" onClick={copy} disabled={!sql}>
            {copied ? "Kopyalandı" : "Kopyala"}
          </button>
        </div>
        <dl className="evidence-meta">
          <div>
            <dt>Mod</dt>
            <dd>{formatCell(payload?.mode)}</dd>
          </div>
          <div>
            <dt>Tablolar</dt>
            <dd>{join(payload?.tables_used)}</dd>
          </div>
          <div>
            <dt>Kurallar</dt>
            <dd>{join(payload?.rules_used)}</dd>
          </div>
          <div>
            <dt>Maskeli kolonlar</dt>
            <dd>{join(payload?.masked_columns)}</dd>
          </div>
          {timings && (
            <div>
              <dt>Süre</dt>
              <dd>{timings}</dd>
            </div>
          )}
          <div>
            <dt>Denetim kaydı</dt>
            <dd className="audit-id">{formatCell(payload?.audit_id)}</dd>
          </div>
        </dl>
        {facts.length > 0 && (
          <ul className="facts">
            {facts.map((fact, index) => (
              <li key={`${index}-${fact.name ?? ""}`}>
                <span className="fact-label">{fact.label}</span>
                <span className="fact-value">{fact.display || formatCell(fact.value)}</span>
              </li>
            ))}
          </ul>
        )}
        {steps.length > 0 && (
          <ol className="steps">
            {steps.map((step, index) => (
              <li key={index} className={step.ok ? "step" : "step step-failed"}>
                <span className="step-mark" aria-hidden="true">
                  {step.ok ? "✓" : "✗"}
                </span>
                <span className="step-tool">{step.tool || "yanıt"}</span>
                <span className="step-summary">{step.summary}</span>
              </li>
            ))}
          </ol>
        )}
        {notes.length > 0 && (
          <ul className="notes">
            {notes.map((note, index) => (
              <li key={index}>{note}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
