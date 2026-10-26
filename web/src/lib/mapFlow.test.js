import { describe, expect, it } from "vitest";
import {
  INDEX_MESSAGE,
  NO_FILE_MESSAGE,
  PROGRESS_STEPS,
  canApply,
  initialMapState,
  mapReducer,
  progressSteps,
  shouldPoll,
} from "./mapFlow.js";

// Sözleşme "preview response" / "apply / status"ın gerçekçi örnekleri: ekran bunları okur.
function previewResponse(overrides = {}) {
  return {
    preview_id: "p-1",
    dataset: { name: "ornek_fatura", display_name: "Örnek Fatura", connection: "mssql" },
    counts: { tables: 1, columns: 12, pii: 2, deny: 1, references: 3, rules: 4 },
    errors: [],
    warnings: [],
    db_check: { checked: false, message: null },
    ...overrides,
  };
}

const job = (phase, message = null) => ({ preview_id: "p-1", name: "ornek_fatura", phase, message });

function run(actions, state = initialMapState) {
  const steps = [{ ...state, n: 0 }];
  for (const action of actions) steps.push(mapReducer(steps.at(-1), action));
  return steps;
}

describe("mapReducer geçişleri", () => {
  it("boş çağrı boş durumu verir", () => {
    expect(mapReducer().status).toBe("idle");
    expect(mapReducer(initialMapState, { type: "bilinmeyen" })).toBe(initialMapState);
  });

  it("seçmeden etkinleştirmeye kadar her geçiş sırayla döner", () => {
    const steps = run([
      { type: "select", filename: "harita.xlsx" },
      { type: "preview" },
      { type: "previewed", preview: previewResponse() },
      { type: "apply" },
      { type: "job", job: job("writing") },
      { type: "job", job: job("indexing") },
      { type: "job", job: job("done") },
      { type: "activated", name: "ornek_fatura" },
    ]);
    expect(steps.map((step) => step.status)).toEqual([
      "idle",
      "idle",
      "previewing",
      "previewed",
      "applying",
      "applying",
      "indexing",
      "done",
      "activated",
    ]);
    expect(steps[2].filename).toBe("harita.xlsx");
    expect(steps[3].preview.counts.tables).toBe(1);
    expect(steps.at(-1).activated).toBe("ornek_fatura");
    expect(steps.at(-1).error).toBeNull();
  });

  it("dosya seçilmeden kontrol sunucuya gitmez, noFile olur", () => {
    const state = mapReducer(initialMapState, { type: "preview" });
    expect(state.status).toBe("noFile");
    expect(state.error).toEqual({ kind: "nofile", message: NO_FILE_MESSAGE });
    expect(canApply(state)).toBe(false);
  });

  it("yeni dosya eski raporu düşürür, noFile cümlesini temizler", () => {
    const reported = mapReducer({ ...initialMapState, status: "noFile" }, { type: "select", filename: "a.xlsx" });
    expect(reported.status).toBe("idle");
    expect(reported.filename).toBe("a.xlsx");
    expect(reported.error).toBeNull();
    const previewed = mapReducer(reported, { type: "previewed", preview: previewResponse() });
    expect(mapReducer(previewed, { type: "select", filename: "b.xlsx" }).preview).toBeNull();
  });

  it("işin aşaması durumu taşır; beklenmedik aşama ekrana dokunmaz", () => {
    const applying = mapReducer({ ...initialMapState, status: "previewed" }, { type: "job", job: job("writing") });
    expect(applying.status).toBe("applying");
    expect(mapReducer(applying, { type: "job", job: job("indexing") }).status).toBe("indexing");
    expect(mapReducer(applying, { type: "job", job: job("done") }).status).toBe("done");
    const broken = mapReducer(applying, { type: "job", job: job("failed", "İndeks kurulumu çöktü.") });
    expect(broken.status).toBe("failed");
    expect(broken.error).toEqual({ kind: "index", message: "İndeks kurulumu çöktü." });
    expect(mapReducer(applying, { type: "job", job: job("yok") })).toBe(applying);
  });

  it("mesajsız başarısızlık genel cümleyle kalır", () => {
    const state = mapReducer({ ...initialMapState, status: "indexing" }, { type: "job", job: job("failed", "") });
    expect(state.error).toEqual({ kind: "index", message: INDEX_MESSAGE });
    const previewFailed = mapReducer({ ...initialMapState, status: "previewing" }, { type: "fail" });
    expect(previewFailed.status).toBe("failed");
    expect(previewFailed.error.kind).toBe("failed");
    expect(previewFailed.error.message).toBe("İşlem tamamlanamadı.");
  });

  it("sunucunun red cümlesi failed içinde aynen okunur", () => {
    const state = mapReducer(
      { ...initialMapState, status: "previewing" },
      { type: "fail", kind: "preview", message: "Yalnız .xlsx dosyası yüklenebilir." },
    );
    expect(state.error).toEqual({ kind: "preview", message: "Yalnız .xlsx dosyası yüklenebilir." });
  });

  it("geçişin iki sonu var: activated ve switchError", () => {
    const done = { ...initialMapState, status: "done", job: job("done") };
    expect(mapReducer(done, { type: "activated" }).activated).toBe("ornek_fatura");
    const failed = mapReducer(done, { type: "switchError", message: "Bu kümenin indeksi yok." });
    expect(failed.status).toBe("switchError");
    expect(failed.error).toEqual({ kind: "switch", message: "Bu kümenin indeksi yok." });
    expect(mapReducer(done, { type: "switchError" }).error.message).toBe("Veri kümesine geçilemedi.");
  });
});

describe("canApply ve yoklama", () => {
  it("hatası olmayan rapor oluşturulabilir", () => {
    expect(canApply({ status: "previewed", preview: previewResponse() })).toBe(true);
  });

  it("hatası olan rapor oluşturulamaz", () => {
    const state = {
      status: "previewed",
      preview: previewResponse({ errors: [{ sheet: "Kolonlar", row: 7, column: "AD", message: "Tablo yok." }] }),
    };
    expect(canApply(state)).toBe(false);
    expect(mapReducer(state, { type: "apply" })).toBe(state);
  });

  it("rapor öncesi ve sonrası durumlar oluşturulamaz", () => {
    for (const status of ["idle", "noFile", "previewing", "applying", "indexing", "done", "failed"]) {
      expect(canApply({ status, preview: previewResponse() })).toBe(false);
    }
    expect(canApply(undefined)).toBe(false);
  });

  it("yoklama done ve failed'da durur", () => {
    const indexing = mapReducer({ ...initialMapState, status: "applying" }, { type: "job", job: job("indexing") });
    expect(shouldPoll(indexing)).toBe(true);
    expect(shouldPoll({ ...initialMapState, status: "applying" })).toBe(true);
    expect(shouldPoll(mapReducer(indexing, { type: "job", job: job("done") }))).toBe(false);
    expect(shouldPoll(mapReducer(indexing, { type: "job", job: job("failed", "oldu") }))).toBe(false);
    for (const status of ["idle", "noFile", "previewing", "previewed", "activated", "switchError"]) {
      expect(shouldPoll({ status })).toBe(false);
    }
  });
});

describe("progressSteps", () => {
  it("adım etiketleri Yazılıyor, İndeks kuruluyor, Hazır", () => {
    expect(PROGRESS_STEPS).toEqual(["Yazılıyor", "İndeks kuruluyor", "Hazır"]);
    expect(progressSteps("writing").map((step) => step.label)).toEqual(PROGRESS_STEPS);
  });

  it("aşama ilerledikçe adım biter, hiç aşamada adım yanmaz", () => {
    const shape = (phase) => progressSteps(phase).map((step) => `${step.done ? "bitti" : ""}${step.active ? "şimdi" : ""}`);
    expect(shape("writing")).toEqual(["şimdi", "", ""]);
    expect(shape("indexing")).toEqual(["bitti", "şimdi", ""]);
    expect(shape("done")).toEqual(["bitti", "bitti", "bitti"]);
    expect(shape("failed")).toEqual(["", "", ""]);
    expect(shape(undefined)).toEqual(["", "", ""]);
  });
});
