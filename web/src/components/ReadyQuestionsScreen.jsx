import { useEffect, useState } from "react";
import * as api from "../lib/api.js";
import { BUSINESS_ROLES, EVERY_ROLE, EVERY_ROLE_LABEL, groupByRole } from "../lib/startCards.js";

// Yöneticinin hazır soru defteri (PLAN R7-21): kümenin bütün satırları burada durur, onaylıları
// kullanıcının panosunda görünür. Satırın SQL'i hiçbir yerde gösterilmez — açma, onay, düzenleme
// ve silme sunucunun kendi yollarıdır, reddin cümlesi değiştirilmeden okunur.
const DISPLAYS = [
  ["number", "Tek sayı"],
  ["chart", "Grafik"],
  ["table", "Tablo"],
];

const DISPLAY_NAMES = new Map(DISPLAYS);

// Rol seçenekleri "Hazır soru yap" formuyla aynı sıra ve aynı adlar: defter yeni bir rol uydurmaz.
// Kişisel satır (business_role null) seçenekte yoktur — onu sahibi panosundan kendisi ekler.
const ROLES = [[EVERY_ROLE, EVERY_ROLE_LABEL], ...BUSINESS_ROLES.map((item) => [item.role, item.label])];
const ROLE_NAMES = new Map(ROLES);

// Öneri işi sunucuda koşar (R7-20); ekran işi bırakmaz, aşamasını iki saniyede bir sorar.
const JOB_POLL_MS = 2000;

function displayLabel(display) {
  return DISPLAY_NAMES.get(display) ?? String(display ?? "");
}

function count(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function titleOf(row) {
  return String(row?.title ?? "").trim() || `#${row?.id ?? ""}`;
}

// İşin aşaması tek cümle: koşan soru ile aday satır sayısı ayrı ayrı okunur, yoksa "çalışıyor"
// hiçbir şey söylemez.
function jobText(job) {
  const asked = count(job.asked);
  const stored = count(job.stored);
  if (job.phase === "done") return `Öneri bitti: ${asked} soru soruldu, ${stored} aday onay bekliyor.`;
  if (job.phase === "failed") return job.message ? `Öneri tamamlanamadı: ${job.message}` : "Öneri tamamlanamadı.";
  return `Öneri koşuyor: ${asked} soru soruldu, ${stored} aday eklendi.`;
}

function ReadyRow({ row, busy, confirming, draft, handlers }) {
  const pending = !row.approved;
  const editing = Boolean(draft);
  const change = (name) => (event) => handlers.onField(name, event.target.value);
  // Aday satırın başlığı önerinin kendi cümlesidir (ready.py başlığı sorudan uydurur): başlık
  // sorunun aynısıysa gri satır basılmaz, yoksa onay kuyruğunun her satırı aynı cümleyi iki kez sayar.
  const title = titleOf(row);
  const question = String(row.question ?? "").trim();

  return (
    <li className="card ready-row" data-ready-id={row.id}>
      <div className="ready-row-main">
        <h3 className="ready-row-title">
          {title}
          {pending && <span className="users-state ready-badge">Onay bekliyor</span>}
        </h3>
        {question && title !== question && <p className="ready-row-question">{question}</p>}
        <p className="ready-row-meta">
          {[displayLabel(row.display), `sıra ${count(row.position)}`, row.created_by ? String(row.created_by) : ""]
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
          title={pending ? "Onaysız satır panoda görünmez; yönetici ön izlemesidir." : "Cevabı yeni bir konuşmada açılır."}
          onClick={() => handlers.onOpen(row)}
        >
          {pending ? "Önizle" : "Aç"}
        </button>
        {pending && (
          <button
            type="button"
            className="btn btn-primary"
            data-ready-approve={row.id}
            disabled={busy}
            onClick={() => handlers.onApprove(row)}
          >
            Onayla
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
          {editing ? "Vazgeç" : "Düzenle"}
        </button>
        {confirming ? (
          <span className="ready-confirm">
            Silinsin mi?
            <button type="button" className="btn btn-ghost" data-ready-delete-confirm={row.id} disabled={busy} onClick={() => handlers.onRemove(row)}>
              Evet
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => handlers.onCancelConfirm()}>
              Vazgeç
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
            Sil
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
              Başlık
            </label>
            <input
              id="ready-edit-title"
              className="field-input"
              type="text"
              value={draft.title}
              onChange={change("title")}
            />
            <p className="field-hint">Panodaki kartın üstünde okunur.</p>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="ready-edit-role">
              İş rolü
            </label>
            <select id="ready-edit-role" className="field-input" value={draft.business_role} onChange={change("business_role")}>
              {ROLES.map(([role, label]) => (
                <option key={role} value={role}>
                  {label}
                </option>
              ))}
            </select>
            <p className="field-hint">Kart yalnız bu rolün panosunda açılır.</p>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="ready-edit-display">
              Görünüm
            </label>
            <select id="ready-edit-display" className="field-input" value={draft.display} onChange={change("display")}>
              {DISPLAYS.map(([kind, label]) => (
                <option key={kind} value={kind}>
                  {label}
                </option>
              ))}
            </select>
            <p className="field-hint">Kartın yükü bu biçimde çizilir.</p>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="ready-edit-position">
              Sıra
            </label>
            <input
              id="ready-edit-position"
              className="field-input"
              type="number"
              step="1"
              value={draft.position}
              onChange={change("position")}
            />
            <p className="field-hint">Küçük olan önce gelir; eşitlikte eklenme sırası.</p>
          </div>
          <div className="ready-edit-actions">
            <button type="submit" id="ready-edit-save" className="btn btn-primary" disabled={busy}>
              Kaydet
            </button>
            <button type="button" id="ready-edit-cancel" className="btn" onClick={() => handlers.onCancelEdit()}>
              Vazgeç
            </button>
          </div>
        </form>
      )}
    </li>
  );
}

export default function ReadyQuestionsScreen({ rows = [], loading = false, error = "", onRefresh }) {
  const [note, setNote] = useState("");
  const [failure, setFailure] = useState("");
  const [job, setJob] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [confirmId, setConfirmId] = useState(null);
  const [draft, setDraft] = useState(null); // düzenlenen satırın alanları | null: form kapalı

  const list = (Array.isArray(rows) ? rows : []).filter((row) => row?.id !== undefined && row?.id !== null);
  const groups = groupByRole(list);

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
          setFailure(rejected?.message || "Öneri işi izlenemedi.");
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
      setFailure(rejected?.message || "Öneri işi başlatılamadı.");
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
      setFailure(rejected?.message || "İstek tamamlanamadı.");
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
        setFailure("Cevap açılamadı.");
        return;
      }
      window.location.hash = `#/c/${payload.conversation_id}`;
    } catch (rejected) {
      setFailure(rejected?.message || "Cevap açılamadı.");
    } finally {
      setBusyId(null);
    }
  };

  const approve = (row) =>
    guard(row, () => api.readyUpdate(row.id, { approved: true }), `“${titleOf(row)}” onaylandı; kart artık panoda.`);

  const remove = (row) => {
    setConfirmId(null);
    return guard(row, () => api.readyRemove(row.id), `“${titleOf(row)}” silindi.`);
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
      display: DISPLAY_NAMES.has(row.display) ? row.display : "table",
      business_role: ROLE_NAMES.has(row.business_role) ? row.business_role : EVERY_ROLE,
      position: String(count(row.position)),
    });
  };

  const saveEdit = async (row, fields) => {
    const title = String(fields.title ?? "").trim();
    if (!title) {
      setFailure("Başlık boş olamaz.");
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
      `“${title}” güncellendi.`,
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

  // Okuma hatasının cümlesi bantta durur; satır yuvası aynı sözü bir daha saymaz.
  const emptyText = loading
    ? "Hazır sorular okunuyor…"
    : "Henüz hazır soru yok. Bir soru sorup cevabını hazır soru yapabilir ya da “Öneri iste” ile aday üretebilirsiniz.";

  return (
    <section id="ready-screen" className="screen ready-screen">
      <div className="rules-head">
        <div>
          <h1 className="screen-title">Hazır sorular</h1>
          <p className="screen-lead">
            Panodaki kartların defteri: onaylı satırlar kullanıcıların ekranında açılır, onay bekleyenler burada kalır.
          </p>
        </div>
        <button
          type="button"
          id="ready-suggest"
          className="btn btn-primary"
          disabled={job?.phase === "asking"}
          onClick={suggest}
        >
          Öneri iste
        </button>
      </div>

      {job && (
        <p className="rules-note" id="ready-job" role="status">
          {jobText(job)}
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
