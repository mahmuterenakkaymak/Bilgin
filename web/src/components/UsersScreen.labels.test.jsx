// T486 (M28 görsel incelemesi, işçilik 1): telefonda kullanıcı satırının iki select'i çıplak
// iniyordu — üstte "Kullanıcı", altta "Satış" — hangisinin uygulama rolü hangisinin iş rolü
// söylemeden, ve hiç girmemiş hesap "Son giriş" yerinde tek başına bir çizgi taşıyordu. Ad artık
// kontrolün üstünde küçük bir başlık (`.cell-label`), çizginin sözü ise kataloğun cümlesi
// (`users.neverLoggedIn`); ikisi de iki dilde katalogdan okunuyor.
// @vitest-environment jsdom
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import en from "../i18n/en.json";
import { I18nProvider } from "../i18n/index.js";
import tr from "../i18n/tr.json";
import UsersScreen from "./UsersScreen.jsx";

const noop = () => {};
const TURKISH = /[çğıöşüÇĞİÖŞÜ]/;

// Hiç giriş yapmamış hesap: "Son giriş" hücresinin söyleyecek sözü kataloğun cümlesidir.
const USER = { id: 7, username: "kadri", role: "user", business_role: "satis", active: true, last_login_at: null };

// Satır kendi işaretinden bulunur: sütun sırası değişse de ölçüm satıra bakar.
function cells(element) {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(element);
  const row = [...host.querySelectorAll("tbody tr")].find((trElement) => trElement.textContent.includes("kadri"));
  if (!row) throw new Error("satır bulunamadı: kadri");
  return [...row.querySelectorAll("th, td")];
}

const screen = (lang) => (
  <I18nProvider lang={lang}>
    <UsersScreen users={[USER]} onRefresh={noop} />
  </I18nProvider>
);

const rowText = (element) =>
  cells(element)
    .map((cell) => cell.textContent)
    .join(" ");

describe("kullanıcı satırı — selectlerin adı", () => {
  it("dört hücrenin başlığı sırayla satırda duruyor", () => {
    const captions = cells(<UsersScreen users={[USER]} onRefresh={noop} />)
      .map((cell) => cell.querySelector(":scope > .cell-label"))
      .filter(Boolean)
      .map((label) => label.textContent.trim());
    expect(captions).toEqual([
      `${tr["users.col.role"]}:`,
      `${tr["users.col.businessRole"]}:`,
      `${tr["users.col.status"]}:`,
      `${tr["users.col.lastLogin"]}:`,
    ]);
  });

  it("satırın sözü iki rolün adını ayırdediyor", () => {
    const text = rowText(<UsersScreen users={[USER]} onRefresh={noop} />);
    expect(text).toContain(`${tr["users.col.role"]}:`);
    expect(text).toContain(`${tr["users.col.businessRole"]}:`);
  });

  it("hiç girmemiş hesabın satırı çıplak çizgi değil, kataloğun cümlesi", () => {
    const row = cells(<UsersScreen users={[USER]} onRefresh={noop} />);
    const login = row.find((cell) => cell.classList.contains("users-login"));
    expect(login.textContent).toContain(tr["users.neverLoggedIn"]);
    for (const cell of row) expect(cell.textContent.trim()).not.toBe("—");
  });

  it("cümle İngilizce kabukta İngilizce katalogdan okunuyor", () => {
    const text = rowText(screen("en"));
    expect(text).toContain(en["users.neverLoggedIn"]);
    expect(text).not.toMatch(TURKISH);
  });
});
