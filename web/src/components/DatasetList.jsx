import { useEffect, useState } from "react";
import { useT } from "../i18n/index.js";

// Veri kümeleri listesi (R6-19): harita ekranının üçüncü kartı. Hangi kümenin etkin olduğu,
// hangisinin indeksinin bulunduğu ve geçişten sonra kalan son adım burada okunur. Liste üstten
// gelir, geçiş de üstte yapılır — küme değişince başlık, kenar çubuğu ve örnekler de tazelenir.

const CONNECTIONS = { mssql: "SQL Server", sqlite: "SQLite" };

// Duyurunun "bir kez"i tarayıcının deposunda yaşar: sekme kapanıp açılınca da hatırlanmalı, o
// yüzden bileşenin durumunda değil anahtarında durur. Testler ekranı Node'da kuruyor, orada
// localStorage yoktur; okuyamamak "görülmedi" demektir, duyuru bir kez daha boyanır.
const NOTICE_KEY = "bilgin-notice-";

function noticeSeen(name) {
  try {
    return localStorage.getItem(NOTICE_KEY + name) === "1";
  } catch {
    return false;
  }
}

function markNoticeSeen(name) {
  try {
    localStorage.setItem(NOTICE_KEY + name, "1");
  } catch {
    // depo kapalıysa (özel mod) duyuru her geçişte bir kez daha görünür; geçiş engellenmez
  }
}

function text(value) {
  return typeof value === "string" ? value.trim() : "";
}

// İndeksin üç hali de ayrı söylenir: "yok" ile "eski"nin kullanıcuya farklı işi var.
function indexState(item, t) {
  const index = item?.index ?? {};
  if (index.exists && index.fresh === false) {
    return { label: t("dataset.index.stale"), tone: "is-stale", reason: text(index.reason) };
  }
  if (index.exists) return { label: t("dataset.index.ready"), tone: "is-ready", reason: "" };
  return { label: t("dataset.index.missing"), tone: "is-missing", reason: text(index.reason) };
}

export default function DatasetList({
  datasets = [],
  active = "",
  loading = false,
  error = "",
  notice = null,
  busy = "",
  onActivate,
}) {
  const { t } = useT();
  const items = (Array.isArray(datasets) ? datasets : []).filter((item) => text(item?.name));
  // Görünür olan duyuru kendi kopyası: yeni bir geçiş eskisinin yerine geçer, listeyi
  // tazelerken kaybolmaz. Okuma render'da (işaretçi ilk boyamada da görünsün), yazma effect'te.
  const [shown, setShown] = useState(() =>
    notice?.message && notice?.name && !noticeSeen(notice.name) ? notice : null,
  );

  useEffect(() => {
    if (!notice?.message || !notice?.name || noticeSeen(notice.name)) return;
    setShown(notice);
    markNoticeSeen(notice.name);
  }, [notice]);

  const emptyText = error
    ? t("dataset.empty.error")
    : loading
      ? t("dataset.empty.loading")
      : t("dataset.empty.none");

  return (
    <div className="dataset-block">
      {/* Reddin cümlesi listenin üstünde: 409'un sözü sunucunundur, değiştirilmeden okunur. */}
      {error && (
        <p className="dataset-error" id="dataset-error" role="alert">
          {error}
        </p>
      )}
      {shown && (
        <div className="dataset-notice" id="dataset-notice" role="status">
          <p className="dataset-notice-text">{shown.message}</p>
          {text(shown.login_script_url) && (
            <a className="dataset-notice-link" href={shown.login_script_url} download>
              {t("dataset.notice.script")}
            </a>
          )}
        </div>
      )}
      <ul className="dataset-list" id="dataset-list">
        {items.length === 0 && <li className="dataset-empty">{emptyText}</li>}
        {items.map((item) => {
          const index = indexState(item, t);
          const ready = item.index?.exists === true;
          const isActive = item.active === true || text(item.name) === text(active);
          const pending = busy === item.name;
          return (
            <li className="dataset-row" key={item.name}>
              <span className="dataset-name">
                <span className="dataset-display">{text(item.display_name) || item.name}</span>
                {text(item.display_name) && text(item.display_name) !== text(item.name) && (
                  <span className="dataset-id">{item.name}</span>
                )}
              </span>
              <span className="dataset-conn">{CONNECTIONS[item.connection] || text(item.connection) || "—"}</span>
              <span className={`dataset-index ${index.tone}`} title={index.reason || undefined}>
                {index.label}
              </span>
              {isActive ? (
                <span className="dataset-state">{t("dataset.active")}</span>
              ) : (
                <button
                  type="button"
                  className="btn dataset-activate"
                  data-dataset-activate={item.name}
                  disabled={!ready || pending}
                  title={ready ? undefined : t("dataset.activateBlocked")}
                  onClick={() => onActivate?.(item.name)}
                >
                  {pending ? t("dataset.activating") : t("dataset.activate")}
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
