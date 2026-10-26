// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import MastheadNav from "./components/MastheadNav.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const ADMIN = { username: "admin", role: "admin" };

let container;
let root;

function renderNav() {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  act(() => root.render(<MastheadNav route="ask" user={ADMIN} />));
  return container.querySelector(".masthead-nav");
}

// jsdom yerleşim yapmaz: scrollLeft'u gerçek bir değere sabitlemenin tek yolu özelliği tanımak.
function scrollTo(nav, value) {
  Object.defineProperty(nav, "scrollLeft", { configurable: true, writable: true, value });
  act(() => nav.dispatchEvent(new Event("scroll")));
}

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("masthead gezinme kendi kaymasını bildirir", () => {
  it("boyalı satır solda içerik yok durumuyla başlar", () => {
    const nav = renderNav();
    expect(nav.dataset.overflowStart).toBe("false");
  });

  it("scrollLeft'a kaydırıp scroll olayı gönderince öncesinde içerik olduğunu işaretler", () => {
    const nav = renderNav();
    scrollTo(nav, 120);
    expect(nav.dataset.overflowStart).toBe("true");
  });

  it("0'a dönünce scroll olayı işareti temizler", () => {
    const nav = renderNav();
    scrollTo(nav, 120);
    scrollTo(nav, 0);
    expect(nav.dataset.overflowStart).toBe("false");
  });
});
