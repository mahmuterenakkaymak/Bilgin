// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { describe, expect, it } from "vitest";
import { THEMES, applyTheme, nextTheme, readStored, store } from "./theme.js";

// Depolama ve belge Node'da yok: testler sahtelerini veriyor, tema onları tanımıyor.
function fakeStorage(initial = {}) {
  const items = { ...initial };
  return {
    items,
    getItem: (key) => (key in items ? items[key] : null),
    setItem: (key, value) => {
      items[key] = String(value);
    },
  };
}

const throwingStorage = {
  getItem() {
    throw new Error("depolama kapalı");
  },
  setItem() {
    throw new Error("depolama kapalı");
  },
};

function fakeDoc() {
  const attrs = {};
  return {
    attrs,
    documentElement: {
      setAttribute: (name, value) => {
        attrs[name] = value;
      },
      removeAttribute: (name) => {
        delete attrs[name];
      },
    },
  };
}

describe("nextTheme", () => {
  it("temalar sistem → koyu → açık sırasıyla döner", () => {
    expect(THEMES).toEqual(["system", "dark", "light"]);
    expect(nextTheme("system")).toBe("dark");
    expect(nextTheme("dark")).toBe("light");
    expect(nextTheme("light")).toBe("system");
  });

  it("tanınmayan değer döngüyü sistemden başlatır", () => {
    expect(nextTheme("koyu")).toBe("system");
    expect(nextTheme(undefined)).toBe("system");
  });
});

describe("readStored / store", () => {
  it("geçerli değer aynı anahtardan okunur", () => {
    const storage = fakeStorage();
    store(storage, "dark");
    expect(storage.items["bilgin-theme"]).toBe("dark");
    expect(readStored(storage)).toBe("dark");
  });

  it("boş depolama ve geçersiz değer sistem demektir", () => {
    expect(readStored(fakeStorage())).toBe("system");
    expect(readStored(fakeStorage({ "bilgin-theme": "gece" }))).toBe("system");
    expect(readStored(fakeStorage({ "bilgin-theme": "" }))).toBe("system");
  });

  it("okuma ya da yazma patlarsa arayüz patlamaz", () => {
    expect(readStored(throwingStorage)).toBe("system");
    expect(() => store(throwingStorage, "dark")).not.toThrow();
  });

  it("depolama hiç yoksa da sistem döner", () => {
    expect(readStored(undefined)).toBe("system");
    expect(() => store(null, "light")).not.toThrow();
  });
});

describe("applyTheme", () => {
  it("koyu ve açık kök niteliğe yazılır, sistem niteliği kaldırır", () => {
    const doc = fakeDoc();
    applyTheme(doc, "dark");
    expect(doc.attrs["data-theme"]).toBe("dark");
    applyTheme(doc, "light");
    expect(doc.attrs["data-theme"]).toBe("light");
    applyTheme(doc, "system");
    expect(doc.attrs).toEqual({});
  });

  it("belge yoksa sessizce hiçbir şey yapmaz", () => {
    expect(() => applyTheme(undefined, "dark")).not.toThrow();
  });
});
