import { useEffect, useRef } from "react";

// Gezinme satırı kendi kaymasını kendisi bildirir: telefon başlığında satır kaydırılan bir sıra
// (styles.css), ama hangi uçta devamı olduğunu bilmiyor. Odaklanınca tarayıcı satırı kaydırdığı
// için en sık yapılan hareketten sonra "Sor" iki harfe iniyor ve solda devamı olduğunu söyleyen
// hiçbir şey kalmıyordu (users-screen-users-table-390.png). Satır, kaydırılınca solda/devamında
// içerik olup olmadığını veri niteliği olarak üstleniyor; telefon CSS'i kesik uçtaki maskeyi
// bu duruma göre yakıyor.
export default function MastheadNav({ route, user }) {
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
    <nav className="masthead-nav" aria-label="Bölümler" ref={nav}>
      <a className="nav-link" id="nav-ask" href="#/" aria-current={route === "ask" ? "page" : undefined}>
        Sor
      </a>
      <a className="nav-link" id="nav-rules" href="#/kurallar" aria-current={route === "rules" ? "page" : undefined}>
        Kurallar
      </a>
      {/* Harita ve kullanıcı defteri yalnız yöneticiye açık (R6-19): kök kapı rotayı da korur,
          bağlantı gösterilmeyen bir adrese götürmesin. */}
      {user?.role === "admin" && (
        <a className="nav-link" id="nav-map" href="#/harita" aria-current={route === "map" ? "page" : undefined}>
          Veritabanı haritası
        </a>
      )}
      {user?.role === "admin" && (
        <a className="nav-link" id="nav-ready" href="#/hazir-sorular" aria-current={route === "ready" ? "page" : undefined}>
          Hazır sorular
        </a>
      )}
      {user?.role === "admin" && (
        <a className="nav-link" id="nav-users" href="#/kullanicilar" aria-current={route === "users" ? "page" : undefined}>
          Kullanıcılar
        </a>
      )}
    </nav>
  );
}
