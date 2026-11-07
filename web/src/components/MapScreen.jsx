// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { useEffect, useReducer, useRef, useState } from "react";
import { useT } from "../i18n/index.js";
import DatasetList from "./DatasetList.jsx";
import * as api from "../lib/api.js";
import { arrayBufferToBase64 } from "../lib/fileB64.js";
import {
  PROGRESS_STEP_KEYS,
  canApply,
  initialMapState,
  mapReducer,
  progressFlags,
  shouldPoll,
} from "../lib/mapFlow.js";

// Veritabanı haritası ekranı (R6-19): şablonu al, doldur, geri yükle, denetime bak, küme yap.
// Akışın bütün halleri lib/mapFlow.js'in indirgeyicisinde durur; burada yalnız okunur hâle
// işaret ediliyor, ağ çağrıları MapFlow'da. Böylece her hal sunucuya çıkmadan da kurulabiliyor.

const POLL_MS = 1000;
const MAX_WARNINGS = 20;
// ASSUMPTION: blob olarak indirilen şablonun adı Content-Disposition'dan okunamaz (api yalnız
// baytı ve duyuruyu döner), o yüzden sunucunun sabit adı burada da aynı şekilde duruyor.
const TEMPLATE_FILENAME = "bilgin-veritabani-sablonu.xlsx";
const SAMPLE_FILENAME = "ornek_fatura.xlsx";

// Karelerin, adımların ve başlıkların yazısı kataloğunda (R8-20); burada yalnız sıraları duruyor.
const COUNTS = [
  ["tables", "map.count.tables"],
  ["columns", "map.count.columns"],
  ["pii", "map.count.pii"],
  ["deny", "map.count.deny"],
  ["references", "map.count.references"],
  ["rules", "map.count.rules"],
];

const HOW_TO = [
  ["map.how1.title", "map.how1.text"],
  ["map.how2.title", "map.how2.text"],
  ["map.how3.title", "map.how3.text"],
];

function text(value) {
  return typeof value === "string" ? value.trim() : "";
}

// Sayılar yüklenen dosyadan gelir; alan yoksa ekran "undefined" değil 0 okur.
function count(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function blank(value) {
  return value === null || value === undefined || value === "";
}

function cell(value) {
  return blank(value) ? "—" : String(value);
}

// Seçilen dosyanın boyutu: bayt, KB ya da MB; ondalık Türkçe biçimde (2,5 KB).
function formatSize(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n < 0) return "";
  const units = ["B", "KB", "MB"];
  let value = n;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  const rounded = unit === 0 ? String(Math.round(value)) : value.toFixed(1).replace(/\.0$/, "");
  return `${rounded.replace(".", ",")} ${units[unit]}`;
}

function issues(value) {
  return (Array.isArray(value) ? value : []).filter((issue) => text(issue?.message));
}

// Blob'u diske indiren kısa yol: bağlantıyı kurup bir kez tıklamak, nesne adresini sonra bırakmak.
function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// Denetim raporu: sayılar, hatalar, uyarılar ve canlı veritabanıyla karşılaştırmanın sözü.
function Report({ preview }) {
  const { t } = useT();
  const counts = preview.counts ?? {};
  const errors = issues(preview.errors);
  const warnings = issues(preview.warnings);
  const check = preview.db_check ?? null;
  const extra = Math.max(warnings.length - MAX_WARNINGS, 0);
  const differences = check?.checked ? count(check.missing_in_db?.length) + count(check.only_in_db?.length) : 0;
  const name = text(preview.dataset?.name);
  const display = text(preview.dataset?.display_name);

  return (
    <div className="map-report" id="map-report">
      {name && (
        <p className="map-dataset">
          {t("map.willBe")} <strong>{display || name}</strong>
          {display && display !== name ? ` (${name})` : ""}
        </p>
      )}
      <dl className="map-stats">
        {COUNTS.map(([key, label]) => {
          const value = count(counts[key]);
          // Kişisel verinin sıfırdan farklı olması bir sonraki adımı durdurması gereken bir
          // sözdür: kare kehribara döner ki sayı diğer beşinden ayrılsın (renk yeni değil).
          return (
            <div className={key === "pii" && value > 0 ? "map-stat is-warn" : "map-stat"} key={key}>
              <dt>{t(label)}</dt>
              <dd>{value}</dd>
            </div>
          );
        })}
      </dl>
      <p className="map-stats-note" id="map-stats-note">
        {t("map.statsNote")}
      </p>
      {errors.length > 0 && (
        <div className="map-errors-wrap">
          {/* Telefon kartında hücre kendi sütun adını taşır (M28 review 3): söz kataloğun kendi
              satırıdır, CSS'in ürettiği yazı değil — arayüz İngilizceyken Türkçe kalmaz. */}
          <table className="map-errors" id="map-errors">
            <thead>
              <tr>
                <th scope="col">{t("map.col.sheet")}</th>
                <th scope="col">{t("map.col.row")}</th>
                <th scope="col">{t("map.col.column")}</th>
                <th scope="col">{t("map.col.message")}</th>
              </tr>
            </thead>
            <tbody>
              {errors.map((issue, index) => (
                <tr key={`${index}-${text(issue.sheet)}`}>
                  <td className="map-cell-sheet">{cell(issue.sheet)}</td>
                  {/* Satırı/kolonu olmayan sorunda etiket düşer — "Satır: —" okuyucuya cümlenin
                      üstünde ikinci bir sorun gibi okunuyordu (M24 craft 2). ASSUMPTION: hücre
                      yerinde kalıyor, yalnız etiketini yitiriyor; <td> düşerse tablo geniş ekranda
                      mesajı "Satır" başlığının altına kaydırıyor. */}
                  <td className={blank(issue.row) ? "map-cell-blank" : "map-cell-row"}>
                    <span className="cell-label">{`${t("map.col.row")}: `}</span>
                    {cell(issue.row)}
                  </td>
                  <td className={blank(issue.column) ? "map-cell-blank" : "map-cell-col"}>
                    <span className="cell-label">{`${t("map.col.column")}: `}</span>
                    {cell(issue.column)}
                  </td>
                  <td className="map-msg">{issue.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {warnings.length > 0 && (
        <div className="warnings" id="map-warnings" role="status">
          {warnings.slice(0, MAX_WARNINGS).map((issue, index) => (
            <p className="warning" key={`${index}-${text(issue.sheet)}`}>
              <span className="warning-mark" aria-hidden="true">
                ⚠
              </span>
              <span>{issue.message}</span>
            </p>
          ))}
          {extra > 0 && <p className="map-more">{t("map.more", { count: extra })}</p>}
        </div>
      )}
      <p className="map-db" id="map-db">
        {check?.checked
          ? differences
            ? t("map.db.compared", { count: differences })
            : t("map.db.noDiff")
          : text(check?.message) || t("map.db.none")}
      </p>
    </div>
  );
}

// Kartın numarası adımın hâlini taşır: sürerken vurgu, bitende yerini tik alır — üç kartlık
// işin nerede olduğu başlıktan okunur; sırası gelmeyende numara kendi renginde kalır.
function CardTitle({ n, step, children }) {
  return (
    <h2 className="map-card-title">
      <span className="map-card-n" aria-hidden="true">
        {step === "done" ? "✓" : n}
      </span>
      {" · "}
      {children}
    </h2>
  );
}

export default function MapScreen({
  state = initialMapState,
  info = null,
  datasets = [],
  active = "",
  datasetsLoading = false,
  datasetsError = "",
  notice = null,
  busy = "",
  activating = false,
  downloading = false,
  sampling = false,
  note = null,
  fileName = "",
  onTemplateDb,
  onSample,
  onFile,
  onPreview,
  onApply,
  onActivate,
  onSwitch,
}) {
  const { t } = useT();
  const preview = state.preview;
  const blocked = state.status === "previewed" && issues(preview?.errors).length > 0;
  // İş başladıysa adım bandı konuşur. Reddin cümlesi geçişte her zaman, işte yalnız iş
  // başlamadıysa bu kartın altında durur — başladıysa sözü adım bandının yanındaki cümle söyler.
  const running = state.status === "applying" || Boolean(state.job);
  // İndirgeyicinin kendi cümlesi bir katalog anahtarı ya da çevirisinin kendisidir; sunucunun
  // cümlesi tanımadığı bir yazı olduğu için geldiği dilde kalır (t() onu olduğu gibi bırakır).
  const own = (message) => t(message);
  const alert =
    state.status === "switchError" || (state.status === "failed" && !state.job) ? own(text(state.error?.message)) : "";
  // Üç kartın sırası ekranın zaten bildiğinden okunur ve her kart kendi işinin bitişinden tik
  // alır: dosya seçilince 1, rapor hatasız dönünce 2, kurulan küme listeye düşünce 3. Yoksa bant
  // süs gibi duruyordu — rapor temiz dönse de küme kurulsa da 2 ve 3 numarasında kalıyordu.
  const taken = Boolean(state.filename);
  const checked = Boolean(preview) && issues(preview.errors).length === 0;
  const created = state.status === "done" || state.status === "activated";
  // ASSUMPTION: tik yalnız işi biten kümenin listeye düşmesiyle yanar; önizlemenin adı henüz
  // var olmayan bir kümenin adıyla aynıysa (aynı şablon ikinci kez) liste 3'ü yakmamalı.
  const made = text(state.activated) || text(state.job?.name) || text(preview?.dataset?.name);
  const listed = created && Boolean(made) && datasets.some((item) => text(item?.name) === made);
  const steps = [
    taken ? "done" : "current",
    checked ? "done" : taken ? "current" : "todo",
    listed ? "done" : created || checked ? "current" : "todo",
  ];

  return (
    <section id="map-screen" className="screen map-screen">
      <div>
        <h1 className="screen-title">{t("map.title")}</h1>
        <p className="screen-lead">{t("map.lead")}</p>
      </div>

      <div className="card map-card" data-step-state={steps[0]}>
        <CardTitle n={1} step={steps[0]}>
          {t("map.card1")}
        </CardTitle>
        <ol className="map-steps">
          {HOW_TO.map(([title, hint], index) => (
            <li className="map-step" key={title}>
              <span className="map-step-n">{index + 1}</span>
              <span className="map-step-title">{t(title)}</span>
              <span className="map-step-text">{t(hint)}</span>
            </li>
          ))}
        </ol>
        <div className="map-actions">
          {/* Şablonun adresi dili sorgu parametresinden okur (R8-12): <a> başlık gönderemez.
            Ekran dili kullandığı için bağlantı dil değişince baştan kuruluyor. */}
          <a className="btn" id="map-template" href={api.mapTemplateUrl(false)} download>
            {t("map.template")}
          </a>
          {info?.db_connection === true && (
            <button type="button" className="btn" id="map-template-db" onClick={onTemplateDb} disabled={downloading}>
              {downloading ? t("map.templateDbBusy") : t("map.templateDb")}
            </button>
          )}
          <button type="button" className="btn" id="map-try-sample" onClick={onSample} disabled={sampling}>
            {sampling ? t("map.sampleBusy") : t("map.sample")}
          </button>
        </div>
        {note && (
          <p
            className={`map-note${note.tone === "error" ? " is-error" : note.tone === "ok" ? " is-ok" : ""}`}
            id="map-note"
            role={note.tone === "error" ? "alert" : "status"}
          >
            {note.text}
          </p>
        )}
      </div>

      <div className="card map-card" data-step-state={steps[1]}>
        <CardTitle n={2} step={steps[1]}>
          {t("map.card2")}
        </CardTitle>
        <label className="field-label" htmlFor="map-file">
          {t("map.fileLabel")}
        </label>
        <div className="map-file-row">
          <input
            id="map-file"
            className="map-file"
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={onFile}
          />
          <label className="btn map-file-btn" htmlFor="map-file">
            {t("map.filePick")}
          </label>
          <span className="map-file-name" id="map-file-name">
            {fileName}
          </span>
        </div>
        <div className="map-actions">
          <button
            type="button"
            id="map-preview"
            className="btn btn-primary"
            onClick={onPreview}
            disabled={state.status === "previewing"}
          >
            {state.status === "previewing" ? t("map.previewing") : t("map.preview")}
          </button>
        </div>
        {!state.filename && (
          <p className={state.status === "noFile" ? "map-hint is-alert" : "map-hint"} id="map-hint">
            {t("map.nofile")}
          </p>
        )}
        {preview && <Report preview={preview} />}
        {state.status === "previewed" && (
          <div className="map-actions">
            <button type="button" id="map-apply" className="btn btn-primary" onClick={onApply} disabled={!canApply(state)}>
              {t("map.apply")}
            </button>
            {blocked && (
              <p className="map-hint is-alert" id="map-apply-note">
                {t("map.applyBlocked")}
              </p>
            )}
          </div>
        )}
        {running && (
          <div className="map-progress" id="map-progress" role="status" aria-live="polite">
            {state.status === "failed" ? (
              <p className="map-failure">{own(text(state.error?.message))}</p>
            ) : (
              <ol className="map-track">
                {progressFlags(state.job?.phase).map((step, index) => (
                  <li className={step.done ? "is-done" : step.active ? "is-active" : ""} key={PROGRESS_STEP_KEYS[index]}>
                    <span className="map-track-mark" aria-hidden="true">
                      {step.done ? "✓" : step.active ? "●" : "○"}
                    </span>
                    {t(PROGRESS_STEP_KEYS[index])}
                  </li>
                ))}
              </ol>
            )}
            {state.status === "done" && (
              <div className="map-actions">
                <button type="button" id="map-activate" className="btn btn-primary" onClick={onActivate} disabled={activating}>
                  {activating ? t("dataset.activating") : t("map.activate")}
                </button>
                {/* Kurulan küme gerçek bir SQL Server'a bakıyorsa soru henüz koşulamaz: girişi
                  yönetici bu ekranın kendisinden doldurur (R7-27). */}
                {text(state.preview?.dataset?.connection) === "mssql" && (
                  <a className="map-connection-link" id="map-connection-link" href="#/baglantilar">
                    {t("map.connectionLink")}
                  </a>
                )}
              </div>
            )}
          </div>
        )}
        {state.status === "activated" && (
          <p className="map-done" id="map-activated">
            {t("map.activated", { name: state.activated })}{" "}
            <a href="#/">{t("map.backToAsk")}</a>
          </p>
        )}
        {alert && (
          <p className="map-error" id="map-error" role="alert">
            {alert}
          </p>
        )}
      </div>

      <div className="card map-card" data-step-state={steps[2]}>
        <CardTitle n={3} step={steps[2]}>
          {t("map.card3")}
        </CardTitle>
        <DatasetList
          datasets={datasets}
          active={active}
          loading={datasetsLoading}
          error={datasetsError}
          notice={notice}
          busy={busy}
          onActivate={onSwitch}
        />
      </div>
    </section>
  );
}

// Ekranın akışı: şablon indirme, yükleme, denetleme, küme kurma ve kümeler arası geçiş.
// `onSwitched` küme değiştiğini App'e söyler — başlık, kenar çubuğu ve örnekler aynı gerçeği
// eski hâliyle söylemesin.
export function MapFlow({ onSwitched }) {
  const { t } = useT();
  const [state, dispatch] = useReducer(mapReducer, initialMapState);
  const [info, setInfo] = useState(null);
  const [list, setList] = useState(null); // {active, datasets} | null: henüz okunmadı
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState("");
  const [activating, setActivating] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [sampling, setSampling] = useState(false);
  const [note, setNote] = useState(null);
  const [picked, setPicked] = useState(null); // seçilen gerçek dosya {name,size}; örnek şablon onu boşaltır
  const [listError, setListError] = useState("");
  const fileRef = useRef(null); // seçilen dosyanın kendisi: baytlar yalnız kontrol edildiğinde okunur

  const refreshList = () =>
    api
      .datasetsList()
      .then((data) => {
        setList({ active: text(data?.active), datasets: Array.isArray(data?.datasets) ? data.datasets : [] });
        setListError("");
      })
      .catch((failure) => setListError(failure?.message || t("map.listFailed")));

  useEffect(() => {
    // Düğme yalnız yoklanabilir bir SQL Server varsa kurulur; bilgi gelmezse hiç görünmez.
    api
      .mapInfo()
      .then((data) => setInfo({ db_connection: data?.db_connection === true }))
      .catch(() => setInfo(null));
    refreshList();
  }, []);

  // İndeks işi bellekte yaşıyor; bittiği ya da düştüğü yoklamadan anlaşılır.
  useEffect(() => {
    const previewId = text(state.preview?.preview_id);
    if (!shouldPoll(state) || !previewId) return undefined;
    const timer = setInterval(() => {
      api
        .mapStatus(previewId)
        .then((job) => dispatch({ type: "job", job }))
        .catch((failure) => dispatch({ type: "fail", kind: "status", message: failure?.message }));
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [state]);

  // Liste işin sonunu kendi başına bilmez — yalnız açılışta ve geçişte okunur. Tazelenmezse yeni
  // küme üstünde "✓ Hazır" yazarken 3. kartta hiç görünmez; düşen iş de yarım bir kümeyi sessizce
  // eksik bırakır. Aşama tek yönlü ilerlediği için her iş bir kez tazelenir.
  const jobPhase = state.job?.phase;
  useEffect(() => {
    if (jobPhase === "done" || jobPhase === "failed") refreshList();
  }, [jobPhase]);

  const runPreview = (filename, content) => {
    dispatch({ type: "preview" });
    if (!filename) return; // indirgeyici noFile'a döndü; sunucuya gidecek bir şey yok
    api
      .mapPreview({ filename, content_b64: content })
      .then((payload) => dispatch({ type: "previewed", preview: payload }))
      .catch((failure) => dispatch({ type: "fail", kind: "preview", message: failure?.message }));
  };

  const preview = () => {
    const file = fileRef.current;
    if (!file) return runPreview("", "");
    file
      .arrayBuffer()
      .then((buffer) => runPreview(file.name, arrayBufferToBase64(buffer)))
      .catch(() => dispatch({ type: "fail", kind: "read", message: t("map.readFailed") }));
  };

  // Dolu örnek doğrudan denetime girer: kullanıcı şablonun nasıl dolduğunu rapor üstünden görür.
  const trySample = () => {
    setSampling(true);
    api
      .mapSampleBlob()
      .then((blob) => blob.arrayBuffer())
      .then((buffer) => {
        fileRef.current = null;
        setPicked(null);
        dispatch({ type: "select", filename: SAMPLE_FILENAME });
        runPreview(SAMPLE_FILENAME, arrayBufferToBase64(buffer));
      })
      .catch((failure) => dispatch({ type: "fail", kind: "sample", message: failure?.message }))
      .finally(() => setSampling(false));
  };

  const templateDb = () => {
    setDownloading(true);
    setNote(null);
    api
      .mapTemplateDownload(true)
      .then(({ blob, note: serverNote }) => {
        saveBlob(blob, TEMPLATE_FILENAME);
        setNote({ tone: serverNote ? "warn" : "ok", text: serverNote ?? t("map.downloaded") });
      })
      .catch((failure) => setNote({ tone: "error", text: failure?.message || t("map.downloadFailed") }))
      .finally(() => setDownloading(false));
  };

  const apply = () => {
    const previewId = text(state.preview?.preview_id);
    if (!previewId) return;
    dispatch({ type: "apply" });
    api
      .mapApply(previewId)
      .then((job) => dispatch({ type: "job", job }))
      .catch((failure) => dispatch({ type: "fail", kind: "apply", message: failure?.message }));
  };

  const switchTo = async (name) => {
    setBusy(name);
    try {
      const result = await api.datasetActivate(name);
      if (result?.notice?.message) setNotice({ ...result.notice, name: text(result.active) || name });
      await refreshList();
      onSwitched?.();
      return { ok: true };
    } catch (failure) {
      return { ok: false, message: failure?.message || t("map.switchFailed") };
    } finally {
      setBusy("");
    }
  };

  const switchFromList = async (name) => {
    const result = await switchTo(name);
    if (!result.ok) setListError(result.message);
  };

  const activate = async () => {
    const name = text(state.job?.name) || text(state.preview?.dataset?.name);
    setActivating(true);
    const result = await switchTo(name);
    setActivating(false);
    dispatch(result.ok ? { type: "activated", name } : { type: "switchError", message: result.message });
  };

  const chooseFile = (event) => {
    const file = event.target.files?.[0] ?? null;
    fileRef.current = file;
    setPicked(file ? { name: file.name, size: file.size } : null);
    dispatch({ type: "select", filename: file?.name ?? "" });
  };

  return (
    <MapScreen
      state={state}
      info={info}
      datasets={list?.datasets ?? []}
      active={list?.active ?? ""}
      datasetsLoading={!list}
      datasetsError={listError}
      notice={notice}
      busy={busy}
      activating={activating}
      downloading={downloading}
      sampling={sampling}
      note={note}
      fileName={picked ? `${picked.name} · ${formatSize(picked.size)}` : ""}
      onTemplateDb={templateDb}
      onSample={trySample}
      onFile={chooseFile}
      onPreview={preview}
      onApply={apply}
      onActivate={activate}
      onSwitch={switchFromList}
    />
  );
}
