// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { useEffect, useState } from "react";
import { useT } from "../i18n/index.js";
import * as api from "../lib/api.js";
import { BUSINESS_ROLE_CODES, EVERY_ROLE, groupByRole, roleLabel } from "../lib/startCards.js";

// Yöneticinin hazır soru defteri (PLAN R7-21): kümenin bütün satırları burada durur, onaylıları
// kullanıcının panosunda görünür. Satırın SQL'i hiçbir yerde gösterilmez — açma, onay, düzenleme
// ve silme sunucunun kendi yollarıdır, reddin cümlesi değiştirilmeden okunur.
const DISPLAYS = [
  ["number", "ready.display.number"],
  ["chart", "ready.display.chart"],
  ["table", "ready.display.table"],
];

const DISPLAY_KEYS = new Map(DISPLAYS);

// Rol seçenekleri "Hazır soru yap" formuyla aynı sıra ve aynı adlar: defter yeni bir rol uydurmaz
// ve adı lib/startCards.js'in `roleLabel`ı söyler. Kişisel satır (business_role null) seçenekte
// yoktur — onu sahibi panosundan kendisi ekler.
const ROLES = [EVERY_ROLE, ...BUSINESS_ROLE_CODES];

// Öneri işi sunucuda koşar (R7-20); ekran işi bırakmaz, aşamasını iki saniyede bir sorar.
const JOB_POLL_MS = 2000;

function displayLabel(display, t) {
  const key = DISPLAY_KEYS.get(display);
  return key ? t(key) : String(display ?? "");
}

function count(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function titleOf(row) {
  return String(row?.title ?? "").trim() || `#${row?.id ?? ""}`;
}

// "Yalnız bekleyenler" süzgecinin adresi: yol aynı kalır (route.js sorgu imini yok sayar), yalnız
// `pending=1` işareti eklenir — yenileyince de aynı liste gelir, yoksa süzgeç bir tıklık olurdu.
function readPendingFilter() {
  if (typeof window === "undefined") return false;
  const query = String(window.location.hash || "").split("?")[1] ?? "";
  return new URLSearchParams(query).get("pending") === "1";
}

function writePendingFilter(on) {
  if (typeof window === "undefined") return;
  const path = String(window.location.hash || "").split("?")[0] || "#/hazir-sorular";
  window.location.hash = on ? `${path}?pending=1` : path;
}

// İşin aşaması tek cümle: koşan soru ile aday satır sayısı ayrı ayrı okunur, yoksa "çalışıyor"
// hiçbir şey söylemez.
function jobText(job, t) {
  const asked = count(job.asked);
  const stored = count(job.stored);
  if (job.phase === "done") return t("ready.job.done", { asked, stored });
  if (job.phase === "failed") {
    return job.message ? t("ready.job.failed", { message: job.message }) : t("ready.job.failedPlain");
  }
  return t("ready.job.asking", { asked, stored });
}

function ReadyRow({ row, busy, confirming, draft, handlers }) {
  const { lang, t } = useT();
  const pending = !row.approved;
  const editing = Boolean(draft);
  const change = (name) => (event) => handlers.onField(name, event.target.value);
  // Aday satırın başlığı önerinin kendi cümlesidir (ready.py başlığı sorudan uydurur): başlık
  // sorunun aynısıysa gri satır basılmaz, yoksa onay kuyruğunun her satırı aynı cümleyi iki kez sayar.
  const title = titleOf(row);
  const question = String(row.question ?? "").trim();

  return (
    <li className="card ready-row" data-ready-id={row.id} data-ready-approved={pending ? undefined : "1"}>
      <div className="ready-row-main">
        <h3 className="ready-row-title">
          {title}
          {pending && <span className="users-state ready-badge">{t("ready.pending")}</span>}
        </h3>
        {question && title !== question && <p className="ready-row-question">{question}</p>}
        <p className="ready-row-meta">
          {[displayLabel(row.display, t), t("ready.order", { count: count(row.position) }), row.created_by ? String(row.created_by) : ""]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </div>

      <div className="ready-row-actions">
        {/* ASSUMPTION: açmanın tek yolu POST /api/start/cards/{id}/open'dır; onaysız satırda yürütme
            kararını sunucu verir ve reddin cümlesi satırın altında okunur — ekran yürütmeyi kendi
            başına denemez, ön izleme düğmesi bu yüzden "Önizle" diye anılır. */}
        <button
          type="button"
          className="btn btn-ghost"
          data-ready-open={row.id}
          disabled={busy}
          title={pending ? t("ready.preview.title") : t("ready.open.title")}
          onClick={() => handlers.onOpen(row)}
        >
          {pending ? t("ready.preview") : t("ready.open")}
        </button>
        {pending && (
          <button
            type="button"
            className="btn btn-primary"
            data-ready-approve={row.id}
            disabled={busy}
            onClick={() => handlers.onApprove(row)}
          >
            {t("ready.approve")}
          </button>
        )}
        <button
          type="button"
          className="btn btn-ghost"
          data-ready-edit={row.id}
          disabled={busy}
          aria-expanded={editing}
          onClick={() => (editing ? handlers.onCancelEdit() : handlers.onEdit(row))}
        >
          {editing ? t("ready.cancel") : t("ready.edit")}
        </button>
        {confirming ? (
          <span className="ready-confirm">
            {t("ready.confirmDelete")}
            <button type="button" className="btn btn-ghost" data-ready-delete-confirm={row.id} disabled={busy} onClick={() => handlers.onRemove(row)}>
              {t("ready.confirmYes")}
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => handlers.onCancelConfirm()}>
              {t("ready.cancel")}
            </button>
          </span>
        ) : (
          <button
            type="button"
            className="btn btn-ghost"
            data-ready-delete={row.id}
            disabled={busy}
            onClick={() => handlers.onConfirm(row)}
          >
            {t("ready.delete")}
          </button>
        )}
      </div>

      {editing && (
        <form
          className="ready-edit"
          onSubmit={(event) => {
            event.preventDefault();
            handlers.onSaveEdit(row, draft);
          }}
        >
          <div className="field">
            <label className="field-label" htmlFor="ready-edit-title">
              {t("ready.field.title")}
            </label>
            <input
              id="ready-edit-title"
              className="field-input"
              type="text"
              value={draft.title}
              onChange={change("title")}
            />
            <p className="field-hint">{t("ready.hint.title")}</p>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="ready-edit-role">
              {t("ready.field.role")}
            </label>
            <select id="ready-edit-role" className="field-input" value={draft.business_role} onChange={change("business_role")}>
              {ROLES.map((role) => (
                <option key={role} value={role}>
                  {roleLabel(role, lang)}
                </option>
              ))}
            </select>
            <p className="field-hint">{t("ready.hint.role")}</p>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="ready-edit-display">
              {t("ready.field.display")}
            </label>
            <select id="ready-edit-display" className="field-input" value={draft.display} onChange={change("display")}>
              {DISPLAYS.map(([kind, key]) => (
                <option key={kind} value={kind}>
                  {t(key)}
                </option>
              ))}
            </select>
            <p className="field-hint">{t("ready.hint.display")}</p>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="ready-edit-position">
              {t("ready.field.position")}
            </label>
            <input
              id="ready-edit-position"
              className="field-input"
              type="number"
              step="1"
              value={draft.position}
              onChange={change("position")}
            />
            <p className="field-hint">{t("ready.hint.position")}</p>
          </div>
          <div className="ready-edit-actions">
            <button type="submit" id="ready-edit-save" className="btn btn-primary" disabled={busy}>
              {t("ready.save")}
            </button>
            <button type="button" id="ready-edit-cancel" className="btn" onClick={() => handlers.onCancelEdit()}>
              {t("ready.cancel")}
            </button>
          </div>
        </form>
      )}
    </li>
  );
}

export default function ReadyQuestionsScreen({ rows = [], loading = false, error = "", onRefresh }) {
  const { lang, t } = useT();
  const [note, setNote] = useState("");
  const [failure, setFailure] = useState("");
  const [job, setJob] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [confirmId, setConfirmId] = useState(null);
  const [draft, setDraft] = useState(null); // düzenlenen satırın alanları | null: form kapalı
  const [onlyPending, setOnlyPending] = useState(readPendingFilter); // süzgecin hali adreste durur

  const list = (Array.isArray(rows) ? rows : []).filter((row) => row?.id !== undefined && row?.id !== null);
  const pendingCount = list.reduce((total, row) => total + (row.approved ? 0 : 1), 0);
  // Onay bekleyenler grubun başına geçer (M28 review 4): yöneticinin iş yapabildiği satırlar,
  // onaylıların arasında kaybolmaz. Süzgeç açığıysa onaylı satır hiç listelenmez.
  const visible = onlyPending ? list.filter((row) => !row.approved) : list;
  const groups = groupByRole(visible, lang).map((group) => ({
    ...group,
    items: [...group.items].sort((a, b) => Number(Boolean(a.approved)) - Number(Boolean(b.approved))),
  }));

  // Aday satırlar iş bittiğinde depoya yazılmış olur: işin sözü ekranda kalsın, liste baştan
  // okunsun, yoksa "9 aday eklendi" diyen ekranın altında dokuz satır görünmez.
  useEffect(() => {
    if (job?.phase !== "asking") return undefined;
    const timer = setTimeout(() => {
      api
        .readySuggestStatus(job.job_id)
        .then((data) => {
          setJob(data);
          if (data?.phase === "done") onRefresh?.();
        })
        .catch((rejected) => {
          setJob(null);
          setFailure(rejected?.message || t("ready.job.watchFailed"));
        });
    }, JOB_POLL_MS);
    return () => clearTimeout(timer);
  }, [job]);

  const suggest = async () => {
    setNote("");
    setFailure("");
    try {
      setJob(await api.readySuggest());
    } catch (rejected) {
      setFailure(rejected?.message || t("ready.suggest.failed"));
    }
  };

  // Satır işlerinin ortak hali: düğmeler yalnız o satır için susar, reddin cümlesi bandın
  // sözü olur, başarıdan sonra liste sunucudaki halini göstersin diye aynı istek yinelenir.
  const guard = async (row, work, done) => {
    setBusyId(row.id);
    setNote("");
    setFailure("");
    try {
      await work();
      setNote(done);
      onRefresh?.();
      return true;
    } catch (rejected) {
      setFailure(rejected?.message || t("ready.failed"));
      return false;
    } finally {
      setBusyId(null);
    }
  };

  const open = async (row) => {
    setBusyId(row.id);
    setNote("");
    setFailure("");
    try {
      const payload = await api.startOpen(row.id);
      if (!payload?.conversation_id) {
        setFailure(t("ready.open.failed"));
        return;
      }
      window.location.hash = `#/c/${payload.conversation_id}`;
    } catch (rejected) {
      setFailure(rejected?.message || t("ready.open.failed"));
    } finally {
      setBusyId(null);
    }
  };

  const approve = (row) => guard(row, () => api.readyUpdate(row.id, { approved: true }), t("ready.approved", { title: titleOf(row) }));

  const remove = (row) => {
    setConfirmId(null);
    return guard(row, () => api.readyRemove(row.id), t("ready.deleted", { title: titleOf(row) }));
  };

  const edit = (row) => {
    setNote("");
    setFailure("");
    setDraft({
      // Kimlik formla birlikte taşınır: form aynı anda bir satırda açıktır, alan adları da
      // (ready-edit-title) o yüzden benzersizdir.
      id: row.id,
      title: String(row.title ?? ""),
      // Satırda tanınmayan bir kod varsa form onu olduğu gibi taşır: kaydet, görüneni yazmış olur.
      display: DISPLAY_KEYS.has(row.display) ? row.display : "table",
      business_role: ROLES.includes(row.business_role) ? row.business_role : EVERY_ROLE,
      position: String(count(row.position)),
    });
  };

  const saveEdit = async (row, fields) => {
    const title = String(fields.title ?? "").trim();
    if (!title) {
      setFailure(t("ready.title.empty"));
      return false;
    }
    const saved = await guard(
      row,
      () =>
        api.readyUpdate(row.id, {
          title,
          display: fields.display,
          business_role: fields.business_role,
          position: count(fields.position),
        }),
      t("ready.updated", { title }),
    );
    if (saved) setDraft(null);
    return saved;
  };

  const handlers = {
    onOpen: open,
    onApprove: approve,
    onRemove: remove,
    onConfirm: (row) => setConfirmId(row.id),
    onCancelConfirm: () => setConfirmId(null),
    onEdit: edit,
    onCancelEdit: () => setDraft(null),
    onSaveEdit: saveEdit,
    onField: (name, value) => setDraft((current) => ({ ...current, [name]: value })),
  };

  const togglePending = () => {
    const next = !onlyPending;
    setOnlyPending(next);
    writePendingFilter(next);
  };

  // Okuma hatasının cümlesi bantta durur; satır yuvası aynı sözü bir daha saymaz. Süzgeç her şeyi
  // gizliyorsa "hiç soru yok" değil "bekleyen yok" okunur — onaylılar yerlerinde duruyor.
  const emptyText = loading ? t("ready.empty.loading") : onlyPending ? t("ready.empty.filtered") : t("ready.empty.none");

  return (
    <section id="ready-screen" className="screen ready-screen">
      <div className="rules-head">
        <div>
          <h1 className="screen-title">{t("ready.title")}</h1>
          <p className="screen-lead">{t("ready.lead")}</p>
        </div>
        <button
          type="button"
          id="ready-suggest"
          className="btn btn-primary"
          disabled={job?.phase === "asking"}
          onClick={suggest}
        >
          {t("ready.suggest")}
        </button>
      </div>

      {list.length > 0 && (
        <button
          type="button"
          id="ready-filter-pending"
          className="btn ready-filter"
          aria-pressed={onlyPending}
          title={t("ready.filter.title")}
          onClick={togglePending}
        >
          {t("ready.filter.pending")}
          <span className="ready-filter-count">{pendingCount}</span>
        </button>
      )}

      {job && (
        <p className="rules-note" id="ready-job" role="status">
          {jobText(job, t)}
        </p>
      )}
      {failure && (
        <p className="users-error" id="ready-error" role="alert">
          {failure}
        </p>
      )}
      {!failure && note && (
        <p className="users-note users-band" id="ready-note" role="status">
          {note}
        </p>
      )}
      {error && !failure && (
        <p className="users-error" id="ready-read-error" role="alert">
          {error}
        </p>
      )}

      {groups.length === 0 && !error && (
        <p className="table-empty" id="ready-empty">
          {emptyText}
        </p>
      )}

      {groups.map((group) => (
        <section className="ready-group" key={group.role || "personal"} data-ready-group={group.role || "personal"}>
          <h2 className="ready-group-title">{group.label}</h2>
          <ul className="ready-list">
            {group.items.map((row) => (
              <ReadyRow
                key={row.id}
                row={row}
                busy={busyId === row.id}
                confirming={confirmId === row.id}
                draft={draft?.id === row.id ? draft : null}
                handlers={handlers}
              />
            ))}
          </ul>
        </section>
      ))}
    </section>
  );
}
