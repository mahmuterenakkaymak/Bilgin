// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { describe, expect, it } from "vitest";
import { parseRoute } from "./route.js";

describe("parseRoute", () => {
  it("açılış ve kök hash soru ekranına gider", () => {
    expect(parseRoute("")).toBe("ask");
    expect(parseRoute("#")).toBe("ask");
    expect(parseRoute("#/")).toBe("ask");
    expect(parseRoute(undefined)).toBe("ask");
  });

  it("#/kurallar kural ekranına gider", () => {
    expect(parseRoute("#/kurallar")).toBe("rules");
    expect(parseRoute("#kurallar")).toBe("rules");
    expect(parseRoute("#/kurallar/")).toBe("rules");
    expect(parseRoute("#/KURALLAR")).toBe("rules");
  });

  it("tanınmayan her hash soru ekranına düşer", () => {
    expect(parseRoute("#/ayarlar")).toBe("ask");
    expect(parseRoute("#/kurallar/ekle")).toBe("ask");
    expect(parseRoute("rasgele metin")).toBe("ask");
  });
});
