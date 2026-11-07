// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { useEffect, useRef } from "react";
import { useT } from "../i18n/index.js";

// Gezinme satırı kendi kaymasını kendisi bildirir: telefon başlığında satır kaydırılan bir sıra
// (styles.css), ama hangi uçta devamı olduğunu bilmiyor. Odaklanınca tarayıcı satırı kaydırdığı
// için en sık yapılan hareketten sonra "Sor" iki harfe iniyor ve solda devamı olduğunu söyleyen
// hiçbir şey kalmıyordu (users-screen-users-table-390.png). Satır, kaydırılınca solda/devamında
// içerik olup olmadığını veri niteliği olarak üstleniyor; telefon CSS'i kesik uçtaki maskeyi
// bu duruma göre yakıyor.
// Bağlantının gördüğü ad kısa (`nav.*`), tam adı `title` ve erişim adı (`navfull.*`): satır
// ikinci kata çıktığında da ekran okuyucu gittiği yeri tam söylüyor.
export default function MastheadNav({ route, user }) {
  const { t } = useT();
  const nav = useRef(null);

  useEffect(() => {
    const el = nav.current;
    if (!el) return undefined;
    const report = () => {
      el.dataset.overflowStart = el.scrollLeft > 0 ? "true" : "false";
      el.dataset.overflowEnd = el.scrollLeft + el.clientWidth < el.scrollWidth ? "true" : "false";
    };
    report();
    el.addEventListener("scroll", report, { passive: true });
    window.addEventListener("resize", report);
    return () => {
      el.removeEventListener("scroll", report);
      window.removeEventListener("resize", report);
    };
  }, [route, user?.role]);

  return (
    <nav className="masthead-nav" aria-label={t("nav.sections")} ref={nav}>
      <a className="nav-link" id="nav-ask" href="#/" title={t("navfull.ask")} aria-label={t("navfull.ask")} aria-current={route === "ask" ? "page" : undefined}>
        {t("nav.ask")}
      </a>
      <a className="nav-link" id="nav-rules" href="#/kurallar" title={t("navfull.rules")} aria-label={t("navfull.rules")} aria-current={route === "rules" ? "page" : undefined}>
        {t("nav.rules")}
      </a>
      {/* Harita ve kullanıcı defteri yalnız yöneticiye açık (R6-19): kök kapı rotayı da korur,
          bağlantı gösterilmeyen bir adrese götürmesin. */}
      {user?.role === "admin" && (
        <a className="nav-link" id="nav-map" href="#/harita" title={t("navfull.map")} aria-label={t("navfull.map")} aria-current={route === "map" ? "page" : undefined}>
          {t("nav.map")}
        </a>
      )}
      {/* Bağlantılar da haritanın yanı: küme orada kuruluyor, girişi burada dolduruluyor (R7-27). */}
      {user?.role === "admin" && (
        <a className="nav-link" id="nav-connections" href="#/baglantilar" title={t("navfull.connections")} aria-label={t("navfull.connections")} aria-current={route === "connections" ? "page" : undefined}>
          {t("nav.connections")}
        </a>
      )}
      {user?.role === "admin" && (
        <a className="nav-link" id="nav-ready" href="#/hazir-sorular" title={t("navfull.ready")} aria-label={t("navfull.ready")} aria-current={route === "ready" ? "page" : undefined}>
          {t("nav.ready")}
        </a>
      )}
      {user?.role === "admin" && (
        <a className="nav-link" id="nav-users" href="#/kullanicilar" title={t("navfull.users")} aria-label={t("navfull.users")} aria-current={route === "users" ? "page" : undefined}>
          {t("nav.users")}
        </a>
      )}
    </nav>
  );
}
