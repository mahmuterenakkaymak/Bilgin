// Başlığın veritabanı noktası ve düşmüş veritabanının bandı (PLAN R7-27).
//
// İkisi de /api/health'ın `db` bloğunu okur (Contracts "health db"): nokta arka plan
// yoklamasının son cevabıdır, yani onu göstermek hiçbir `SELECT 1` beklemez. Kullanıcı tek genel
// cümleyi okur; yönetici sürücünün kendi cümlesini de alır ve noktanın adı onun elinde bağlantıya
// döner — sunucu `message_admin`i zaten yalnız yöneticiye gönderiyor (web/app.py `_db_block`).
// Bant yalnız `down` halinde açılır ve ekranın üstünde kendi yerini alır: soru kutusu altında
// durmaya devam eder, çünkü soru koşmaz ama yazılmaktan da alıkonulmaz.

const SENTENCES = {
  ok: "Veritabanı yanıt veriyor.",
  down: "Veritabanına bağlanılamıyor, yöneticinize haber verin.",
  none: "Bu veri kümesinin veritabanı bağlantısı yok.",
  unknown: "Veritabanı durumu henüz ölçülmedi.",
};

const LABEL = "Veritabanı";
const CONNECTIONS_URL = "#/baglantilar";

function text(value) {
  return typeof value === "string" ? value.trim() : "";
}

// "2026-10-27T09:15:00+00:00" → "27 Ekim 2026 12:15". ASSUMPTION: sunucu UTC yazıyor, dilim
// yalnız gösterim; okunamayan tarih cümleyi kabartmaz, ipucu süresiz de okunur.
function stamp(value) {
  const date = new Date(typeof value === "string" ? value : Number.NaN);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("tr-TR", {
    day: "2-digit",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// Cümle + saat + (yönetici için) sürücü satırı. Sunucunun gönderdiği genel cümle ne varsa odur;
// sabiti yalnız cevap boş kaldığında okunur, iki yer aynı şeyi söylemesin.
export function dbStatus(db, isAdmin = false) {
  const tone = SENTENCES[db?.state] ? db.state : "unknown";
  const sentence = (tone === "down" && text(db?.message)) || SENTENCES[tone];
  const adminMessage = isAdmin ? text(db?.message_admin) : "";
  const time = stamp(db?.checked_at);
  const parts = [sentence, time ? `Son kontrol: ${time}` : "", adminMessage];
  return { tone, label: LABEL, sentence, adminMessage, tip: parts.filter(Boolean).join(" · ") };
}

export function DbDot({ db, isAdmin = false }) {
  const { tone, label, tip } = dbStatus(db, isAdmin);
  // ASSUMPTION: `title` bağlantı taşıyamaz; yöneticinin adresi noktanın adında durur, kullanıcının
  // adı düz sözcük kalır — iki başlıkta da ne okunduğu ile nereye gidildiği karışmaz.
  return (
    <span className="db-status" title={tip}>
      <span className={`db-dot db-dot-${tone}`} id="db-dot" role="img" aria-label={tip} />
      {isAdmin ? (
        <a className="db-label" href={CONNECTIONS_URL}>
          {label}
        </a>
      ) : (
        <span className="db-label">{label}</span>
      )}
    </span>
  );
}

export function DbBanner({ db, isAdmin = false }) {
  const { tone, sentence, adminMessage } = dbStatus(db, isAdmin);
  if (tone !== "down") return null;
  return (
    <p className="db-banner" id="db-banner" role="alert">
      <span className="db-banner-text">{sentence}</span>
      {adminMessage && <span className="db-banner-admin">{adminMessage}</span>}
      {isAdmin && (
        <a className="db-banner-link" href={CONNECTIONS_URL}>
          Bağlantıyı düzenle
        </a>
      )}
    </p>
  );
}
