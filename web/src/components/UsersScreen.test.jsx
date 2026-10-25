// Ekran SSR ile kuruluyor: tablonun işareti (hangi rol seçili, hangi düğme hangi sözcüğü
// söylüyor) boya çıkmadan da okunur. Olaylar — ekleme, pasifleştirme — ağ ister; onların
// karşılığı sunucu tarafında (tests/test_web_users_api.py) zaten koşuluyor.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import App from "../App.jsx";
import UsersScreen from "./UsersScreen.jsx";

const noop = () => {};

// Cümlelerdeki kesme işareti ve tırnak SSR çıktısında düz karakter değildir; okunur metin öyle aranır.
function render(element) {
  return renderToStaticMarkup(element)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&");
}

const screen = (props) => render(<UsersScreen onRefresh={noop} {...props} />);

const USERS = [
  {
    id: 1,
    username: "admin",
    role: "admin",
    active: true,
    created_at: "2026-10-20T09:00:00+00:00",
    last_login_at: "2026-10-26T08:15:00+00:00",
  },
  {
    id: 2,
    username: "analist",
    role: "user",
    active: false,
    created_at: "2026-10-21T09:00:00+00:00",
    last_login_at: null,
  },
];

// Satır, kendi select'inin id'sinden bulunur: sütun sırası değişse de ölçüm satıra bakar.
function row(html, id) {
  return html.split("<tr").find((chunk) => chunk.includes(`data-user-role="${id}"`)) ?? "";
}

describe("UsersScreen", () => {
  it("başlığı, beş sütun adını ve ekleme formunu kurar", () => {
    const html = screen({ users: USERS });
    expect(html).toContain('id="users-screen"');
    expect(html).toContain(">Kullanıcılar</h1>");
    for (const column of ["Kullanıcı", "Rol", "Durum", "Son giriş", "İşlemler"]) {
      expect(html).toContain(`>${column}</th>`);
    }
    expect(html).toContain('id="user-add-form"');
    expect(html).toContain('id="user-new-username"');
    expect(html).toContain('id="user-new-password"');
    expect(html).toContain('id="user-new-password2"');
    expect(html).toContain('id="user-new-role"');
    expect(html).toContain('id="user-add-submit"');
    expect(html).toContain(">Kullanıcıyı ekle</button>");
  });

  it("her satır kullanıcının rolünü seçili getirir, durumunu ve doğru düğme sözcüğünü gösterir", () => {
    const html = screen({ users: USERS });
    expect(row(html, 1)).toMatch(/value="admin"[^>]*selected/);
    expect(row(html, 2)).toMatch(/value="user"[^>]*selected/);
    expect(row(html, 1)).toContain(">Etkin</span>");
    expect(row(html, 2)).toContain(">Pasif</span>");
    expect(row(html, 1)).toContain('data-user-toggle="1">Pasifleştir</button>');
    expect(row(html, 2)).toContain('data-user-toggle="2">Etkinleştir</button>');
    expect(row(html, 1)).toContain('data-user-reset="1"');
    expect(row(html, 1)).toContain(">Parolayı değiştir</button>");
  });

  it("son giriş okunur saat; hiç girmeyen '—' ve ipucusunu taşır", () => {
    const html = screen({ users: USERS });
    expect(row(html, 1)).toContain("2026");
    expect(row(html, 2)).toContain(">—</td>");
    expect(row(html, 2)).toContain("Hiç giriş yapmadı.");
  });

  it("sunucunun reddi #users-error'da kendi cümlesiyle durur", () => {
    const refused = screen({ users: USERS, error: "Bu kullanıcı adı zaten var." });
    expect(refused).toContain('id="users-error"');
    expect(refused).toContain("Bu kullanıcı adı zaten var.");
    expect(screen({ users: USERS })).not.toContain('id="users-error"');
  });

  it("boş liste okuma/boş/düşmüş hallerini ayırır; alanı olmayan satır ekranı bozmaz", () => {
    expect(screen({ users: [], loading: true })).toContain("Kullanıcılar okunuyor…");
    const empty = screen({ users: [] });
    expect(empty).toContain("Henüz kullanıcı yok.");
    expect(empty).not.toContain("okunuyor…");
    // okuma düşünce hücre sonsuza dek "okunuyor…"da kalamaz
    const failed = screen({ users: [], loading: true, error: "Kimlik doğrulama kapalı." });
    expect(failed).toContain("Kullanıcılar okunamadı.");
    expect(failed).not.toContain("okunuyor…");
    expect(screen({ users: [null, {}, USERS[0]] })).not.toMatch(/undefined|null/);
  });
});

describe("App — Kullanıcılar bağlantısı", () => {
  it("yalnız yönetici görür; kullanıcı ve tek kullanıcılı kabuk görmez", () => {
    const admin = render(<App user={{ username: "admin", role: "admin" }} />);
    expect(admin).toContain('id="nav-users"');
    expect(admin).toContain('href="#/kullanicilar"');
    expect(admin).toContain(">Kullanıcılar</a>");

    for (const app of [render(<App user={{ username: "analist", role: "user" }} />), render(<App />)]) {
      expect(app).not.toContain('id="nav-users"');
      expect(app).not.toContain("#/kullanicilar");
    }
  });
});
