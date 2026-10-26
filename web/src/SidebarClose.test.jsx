// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import App from "./App.jsx";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container;
let root;

function renderApp() {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  act(() => root.render(<App />));
  return container;
}

function click(node) {
  act(() => node.dispatchEvent(new MouseEvent("click", { bubbles: true })));
}

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("açık çekmecenin kendi kapatma düğmesi", () => {
  it("açık panel düğmeyi #sidebar içinde taşır", () => {
    const app = renderApp();
    click(app.querySelector("#sidebar-toggle"));
    const close = app.querySelector("#sidebar #sidebar-close");
    expect(close).not.toBeNull();
    expect(close.textContent).toBe("Kapat");
    expect(close.getAttribute("aria-controls")).toBe("sidebar");
  });

  it("düğmeye basmak is-open'ı kaldırır ve toggle'ı kapalıya çevirir", () => {
    const app = renderApp();
    click(app.querySelector("#sidebar-toggle"));
    click(app.querySelector("#sidebar-close"));
    expect(app.querySelector("#sidebar").className).toBe("sidebar");
    expect(app.querySelector("#sidebar-toggle").getAttribute("aria-expanded")).toBe("false");
  });

  it("kapalı çekmecede düğme basılmaz", () => {
    const app = renderApp();
    expect(app.querySelector("#sidebar-close")).toBeNull();
  });
});
