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

function names(items) {
  return (Array.isArray(items) ? items : []).map((item) => String(item ?? "").trim()).filter(Boolean);
}

function join(items) {
  const values = names(items);
  return values.length ? values.join(", ") : "–";
}

// Kapalı özet, panelde ne olduğunu baştan söyler: kaç araç adımı koştuğu ve sorgunun dokunduğu
// tablolar. İkisi de yoksa — henüz koşmamış bir yanıtta — özet başlığın kendisi olarak kalır.
function summaryTail(stepCount, tables) {
  const parts = [];
  if (stepCount > 0) parts.push(`${stepCount} adım`);
  if (tables.length > 0) parts.push(tables.join(", "));
  return parts.join(" · ");
}

// Araç sözlüğü modelin bir sonraki turu için yazılmıştır (tools.py `_unknown`); cevabı bulunan bir
// koşta iş kullanıcıya hiçbir şey söylemez, o yüzden satırda kalmaz.
const TOOL_LIST = /\s*Kullan\p{L}*:\s*[^.]*\./u;

function stepSummary(summary) {
  return String(summary ?? "").replace(TOOL_LIST, "");
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
  // ASSUMPTION: "cevabın kendisi başarılı" AskPayload.status === "answered"dır; cevaplanmamış bir
  // yanıt (failed, needs_clarification, alanı olmayan) adımların işaretini olduğu gibi bırakır.
  const succeeded = payload?.status === "answered";
  const timings = timingsText(payload?.timings);
  const facts = (Array.isArray(payload?.facts) ? payload.facts : []).filter((fact) => fact?.label);
  const steps = (Array.isArray(payload?.steps) ? payload.steps : []).filter(
    (step) => step && (step.tool || step.summary),
  );
  const notes = (Array.isArray(payload?.notes) ? payload.notes : []).filter((note) => String(note ?? "").trim());
  const tail = summaryTail(steps.length, names(payload?.tables_used));

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
          ▸
        </span>
        <span>
          Nasıl hesapladım
          {tail && <span className="evidence-tail">{` · ${tail}`}</span>}
        </span>
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
            {steps.map((step, index) => {
              // Cevabı bulunan bir koşta yalnız araç sözlüğü taşıyan (bilinmeyen araç) hata nötr kalır;
              // gerçek bir SQL hatası cevap bulunsa da ✗ ile okunur.
              const failed = !step.ok && !(succeeded && TOOL_LIST.test(String(step.summary ?? "")));
              const mark = step.ok ? "✓" : failed ? "✗" : "";
              return (
                <li key={index} className={failed ? "step step-failed" : "step"}>
                  {mark && <span className="step-mark" aria-hidden="true">{mark}</span>}
                  <span className="step-tool">{step.tool || "yanıt"}</span>
                  <span className="step-summary">{failed ? step.summary : stepSummary(step.summary)}</span>
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
