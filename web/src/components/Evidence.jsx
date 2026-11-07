// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { useState } from "react";
import { useT } from "../i18n/index.js";
import { chipFacts, factValue } from "../lib/facts.js";
import { formatCell, formatNumber, formatSeconds } from "../lib/format.js";

// "Nasıl hesapladım": cevabın dayanakları — SQL, kullanılan tablolar ve kurallar, maskeler,
// olgular, araç adımları, denetim kaydı ve süreler (R5-18). Gövde hep kurulur, kapanışta
// `hidden` kalır; böylece tarayıcıda bulunabilir kalır ve hiçbir alan akışta kaybolmaz.
const TIMINGS = [
  { key: "agent_s", labelKey: "evidence.timing.agent", unit: "s" },
  { key: "execute_ms", labelKey: "evidence.timing.query", unit: "ms" },
  { key: "narrate_s", labelKey: "evidence.timing.narrate", unit: "s" },
  { key: "total_s", labelKey: "evidence.timing.total", unit: "s" },
];

function names(items) {
  return (Array.isArray(items) ? items : []).map((item) => String(item ?? "").trim()).filter(Boolean);
}

function join(items) {
  const values = names(items);
  return values.length ? values.join(", ") : "–";
}

// Kapalı özet, panelde ne olduğunu baştan söyler: kaç araç adımı koştuğu ve sorgunun dokunduğu
// tablolar. İkisi de yoksa — henüz koşmamış bir yanıtta — özet başlığın kendisi olarak kalır.
function summaryTail(stepCount, tables, t) {
  const parts = [];
  if (stepCount > 0) parts.push(t(stepCount === 1 ? "evidence.steps.one" : "evidence.steps", { count: stepCount }));
  if (tables.length > 0) parts.push(tables.join(", "));
  return parts.join(" · ");
}

// Araç sözlüğü modelin bir sonraki turu için yazılmıştır (tools.py `_unknown`); cevabı bulunan bir
// koşta iş kullanıcıya hiçbir şey söylemez, o yüzden satırda kalmaz.
const TOOL_LIST = /\s*Kullan\p{L}*:\s*[^.]*\./u;

function stepSummary(summary, t) {
  const text = String(summary ?? "").replace(TOOL_LIST, "");
  // run_sql/submit_sql satırların tamamını bir sonraki turundaki modele anlatır; kart tabloyu zaten
  // gösterdiği için panelde yalnız kaç satır döndüğü okunur. " | " yalnız bu dökümün hücre ayracıdır.
  if (!text.includes(" | ")) return text;
  const rows = text.split("\n").filter((line) => line.includes(" | ")).length;
  return t(rows === 1 ? "evidence.stepRows.one" : "evidence.stepRows", { count: rows });
}

// Süreler koşmayan aşamaları hiç yazmaz: 0, "koşmadı" demektir. Saniyenin tek ondalık basamağı
// 0,04'ü "0,0 sn" yapar — okunur bir süre olmadığı için o da yazılmaz.
function timingsText(timings, lang, t) {
  const parts = [];
  for (const { key, labelKey, unit } of TIMINGS) {
    const value = timings?.[key];
    if (typeof value !== "number" || !Number.isFinite(value)) continue;
    if (value < (unit === "ms" ? 0 : 0.05)) continue;
    const label = t(labelKey);
    parts.push(unit === "ms" ? `${label} ${formatNumber(value, lang)} ms` : `${label} ${formatSeconds(value, lang)}`);
  }
  return parts.join(" · ");
}

export default function Evidence({ payload }) {
  const { lang, t } = useT();
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const sql = typeof payload?.sql === "string" ? payload.sql : "";
  // ASSUMPTION: "cevabın kendisi başarılı" AskPayload.status === "answered"dır; cevaplanmamış bir
  // yanıt (failed, needs_clarification, alanı olmayan) adımların işaretini olduğu gibi bırakır.
  const succeeded = payload?.status === "answered";
  const timings = timingsText(payload?.timings, lang, t);
  const steps = (Array.isArray(payload?.steps) ? payload.steps : []).filter(
    (step) => step && (step.tool || step.summary),
  );
  const notes = (Array.isArray(payload?.notes) ? payload.notes : []).filter((note) => String(note ?? "").trim());
  const tail = summaryTail(steps.length, names(payload?.tables_used), t);
  // Bağlamın kanıt satırı (R7-5): cevabın hangi önceki turun hangi değerine dayandığı. Panelden
  // dışarıda durur — kapalıyken de okunmalı, yoksa kanıtın kendisi kullanıcıya hiç görünmez.
  const contextLine = typeof payload?.context?.line === "string" ? payload.context.line.trim() : "";
  // Kartın çip şeridi cevabın özetlerini taşır; panel çipe girmeyen okunur olguları listeler —
  // aynı olgu iki yerde birden okunmaz (chipFacts girdinin kendi referanslarını döndürür).
  const answerLang = typeof payload?.answer_lang === "string" ? payload.answer_lang : "tr";
  const facts = Array.isArray(payload?.facts) ? payload.facts : [];
  const chips = chipFacts(facts);
  const rest = facts.filter((fact) => fact?.label && fact?.display && !chips.includes(fact));

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
      {contextLine && (
        <p id="context-line" className="context-line">
          {contextLine}
        </p>
      )}
      <button
        type="button"
        id="evidence-toggle"
        className="evidence-toggle"
        aria-expanded={open}
        aria-controls="evidence"
        onClick={() => setOpen((value) => !value)}
      >
        <span className="evidence-caret" aria-hidden="true">
          ▸
        </span>
        <span>
          {t("evidence.toggle")}
          {tail && <span className="evidence-tail">{` · ${tail}`}</span>}
        </span>
      </button>
      <div id="evidence" className="evidence-body" hidden={!open}>
        <div className="evidence-sql">
          <pre className="sql-block">
            <code>{sql || "–"}</code>
          </pre>
          <button type="button" id="copy-sql" className="btn btn-ghost" onClick={copy} disabled={!sql}>
            {copied ? t("evidence.copied") : t("evidence.copy")}
          </button>
        </div>
        <dl className="evidence-meta">
          <div>
            <dt>{t("evidence.mode")}</dt>
            <dd>{formatCell(payload?.mode)}</dd>
          </div>
          <div>
            <dt>{t("evidence.tables")}</dt>
            <dd>{join(payload?.tables_used)}</dd>
          </div>
          <div>
            <dt>{t("evidence.rules")}</dt>
            <dd>{join(payload?.rules_used)}</dd>
          </div>
          <div>
            <dt>{t("evidence.masked")}</dt>
            <dd>{join(payload?.masked_columns)}</dd>
          </div>
          {timings && (
            <div>
              <dt>{t("evidence.timings")}</dt>
              <dd>{timings}</dd>
            </div>
          )}
          <div>
            <dt>{t("evidence.audit")}</dt>
            <dd className="audit-id">{formatCell(payload?.audit_id)}</dd>
          </div>
        </dl>
        {rest.length > 0 && (
          <div className="evidence-facts">
            <h3 id="evidence-facts" className="evidence-facts-title">
              {t("evidence.otherFacts")}
            </h3>
            <ul className="facts">
              {rest.map((fact, index) => (
                <li key={`${index}-${fact.name ?? ""}`}>
                  <span className="fact-label">{fact.label}</span>
                  <span className="fact-value">{factValue(fact, lang, answerLang)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {steps.length > 0 && (
          <ol className="steps">
            {steps.map((step, index) => {
              // Cevabı bulunan bir koşta yalnız araç sözlüğü taşıyan (bilinmeyen araç) hata nötr kalır;
              // gerçek bir SQL hatası cevap bulunsa da ✗ ile okunur.
              const failed = !step.ok && !(succeeded && TOOL_LIST.test(String(step.summary ?? "")));
              const mark = step.ok ? "✓" : failed ? "✗" : "";
              return (
                <li key={index} className={failed ? "step step-failed" : "step"}>
                  {mark && <span className="step-mark" aria-hidden="true">{mark}</span>}
                  <span className="step-tool">{step.tool || t("evidence.answerStep")}</span>
                  <span className="step-summary">{failed ? step.summary : stepSummary(step.summary, t)}</span>
                </li>
              );
            })}
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
