// T484 (M28 görsel incelemesi 3): telefonda bağlantı satırı "vitrin_kapali / ● Denenmedi / - / - / - / -"
// okunuyordu — yığılmış hücrenin sütun adını CSS `content: var(--cell-*)` ile üretiyordu ve derlenmiş
// sayfada o yazı düşüyordu. Etiket artık hücrenin kendi öğesi (`.cell-label`); söyleyecek sözü olmayan
// hücre ise çıplak çizgi değil, yığılmış satırda yer tutmayan hücredir (`styles.css` içindeki `.is-blank`).
// ASSUMPTION: çizgi geniş ekranda boş sütunun yerini tutuyor (orada adı başlık söylüyor), o yüzden satırın sözü DOM'da okunur, telefonun düşürdüğü hücre `is-blank` işaretiyle ayrılır.
// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import ConnectionsScreen from "./ConnectionsScreen.jsx";
import UsersScreen from "./UsersScreen.jsx";

const noop = () => {};

// Satır kendi işaretinden bulunur: sütun sırası değişse de ölçüm satıra bakar.
function cells(markup, marker) {
  const host = document.createElement("div");
  host.innerHTML = markup;
  const row = [...host.querySelectorAll("tbody tr")].find((tr) => tr.textContent.includes(marker));
  if (!row) throw new Error(`satır bulunamadı: ${marker}`);
  return [...row.querySelectorAll("th, td")];
}

const labelOf = (row, className) =>
  row
    .find((cell) => cell.classList.contains(className))
    .querySelector(".cell-label")
    .textContent.trim();

// Sözleşme "connection (public)": hiçbir alanı doldurulmamış küme — dört hücrenin de söyleyecek sözü yok.
const CONNECTION = {
  dataset: "vitrin_kapali",
  server: null,
  database: null,
  auth: "sql",
  username: "",
  options: {},
  has_secret: false,
  last_ok_at: null,
  last_error: null,
  state: "none",
  source: "none",
  read_only_form: false,
};

const connectionRow = () =>
  cells(renderToStaticMarkup(<ConnectionsScreen connections={[CONNECTION]} onRefresh={noop} />), "vitrin_kapali");

// Hiç giriş yapmamış hesap: "Son giriş" hücresinin de söyleyecek sözü yok.
const USER = { id: 7, username: "kadri", role: "user", business_role: "genel", active: true, last_login_at: null };

const userRow = () => cells(renderToStaticMarkup(<UsersScreen users={[USER]} onRefresh={noop} />), "kadri");

describe("bağlantı satırı — yığılmış hücrelerin etiketi", () => {
  it("dört sütun adının sözü satırda duruyor", () => {
    const text = connectionRow()
      .map((cell) => cell.textContent)
      .join(" ");
    for (const label of ["Durum", "Sunucu / veritabanı", "Son başarılı", "Son hata"]) {
      expect(text).toContain(label);
    }
  });

  it("her etiketli hücre sözünü kendi öğesinden taşır", () => {
    const row = connectionRow();
    expect(labelOf(row, "conn-status")).toBe("Durum:");
    expect(labelOf(row, "conn-target")).toBe("Sunucu / veritabanı:");
    expect(labelOf(row, "conn-success")).toBe("Son başarılı:");
    expect(labelOf(row, "conn-failure")).toBe("Son hata:");
  });

  it("söyleyecek sözü olmayan hücre çıplak çizgi değildir ve düşeni işaretler", () => {
    for (const cell of connectionRow()) {
      expect(cell.textContent.trim()).not.toBe("—");
      if (cell.textContent.includes("—")) expect(cell.className).toContain("is-blank");
    }
  });
});

describe("kullanıcı satırı — yığılmış hücrelerin etiketi", () => {
  it("dört sütun adının sözü satırda duruyor", () => {
    const text = userRow()
      .map((cell) => cell.textContent)
      .join(" ");
    for (const label of ["Rol", "İş rolü", "Durum", "Son giriş"]) {
      expect(text).toContain(label);
    }
  });

  it("her etiketli hücre sözünü kendi öğesinden taşır", () => {
    const row = userRow();
    expect(labelOf(row, "users-role")).toBe("Rol:");
    expect(labelOf(row, "users-business")).toBe("İş rolü:");
    expect(labelOf(row, "users-status")).toBe("Durum:");
    expect(labelOf(row, "users-login")).toBe("Son giriş:");
  });

  it("söyleyecek sözü olmayan hücre çıplak çizgi değildir ve düşeni işaretler", () => {
    const row = userRow();
    for (const cell of row) {
      expect(cell.textContent.trim()).not.toBe("—");
      if (cell.textContent.includes("—")) expect(cell.className).toContain("is-blank");
    }
    expect(row.some((cell) => cell.classList.contains("users-login"))).toBe(true);
  });
});
