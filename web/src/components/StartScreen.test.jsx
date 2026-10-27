// @vitest-environment jsdom
// Pano hem işaret hem olay ister: kartın yükü üç biçimde boyanır, tıklaması konuşma açar,
// "Yenile"nin 429'u kartın içinde okunur. Yapı SSR ile okunur; ağ ve olay jsdom'da koşar, o
// yüzden grafikli kartlar yalnız markup'ta çizilir (ChartView'ın efekti jsdom'da koşmaz).
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../lib/api.js";
import { columnLabel } from "../lib/chartFormat.js";
import StartCard from "./StartCard.jsx";
import StartScreen from "./StartScreen.jsx";

vi.mock("../lib/api.js", async (importOriginal) => ({
  ...(await importOriginal()),
  start: vi.fn(),
  startRefresh: vi.fn(),
  startOpen: vi.fn(),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const noop = () => {};
const ID = "3f2a9c0d1e4b4a7f8c6d5e2b1a0f9e8d";

function minutesAgo(minutes) {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

// Contracts "start card": yük sunucuda yürümüş hâliyle gelir, SQL hiçbir alanda yoktur.
const NUMBER = {
  id: 11,
  title: "Bu ay net satış",
  question: "Bu ay net satışımız ne kadar?",
  display: "number",
  personal: false,
  value: 8910.5,
  label: "Net satış tutarı",
  refreshed_at: minutesAgo(5),
};

const TABLE = {
  id: 13,
  title: "En çok satan ürünler",
  question: "En çok satan iki ürün hangisi?",
  display: "table",
  personal: true,
  columns: ["ÜRÜN", "ADET"],
  rows: [["Siyah Çay 500 g", 2480], ["Yeşil Çay 500 g", 1900]],
  refreshed_at: null,
};

const CHART = {
  id: 12,
  title: "Ay ay satış",
  question: "Ay ay satış ne kadar?",
  display: "chart",
  personal: false,
  chart: {
    type: "bar",
    option: {
      xAxis: { type: "category", data: ["Ağustos", "Eylül"] },
      yAxis: { type: "value" },
      series: [{ type: "bar", data: [7400, 8910] }],
    },
  },
  refreshed_at: minutesAgo(90),
};

const BROKEN = {
  id: 14,
  title: "Kapanmamış cari bakiyesi",
  question: "Kapanmamış cari bakiyesi ne kadar?",
  display: "number",
  personal: false,
  error: "Bu giriş bu kolonu göremez.",
  refreshed_at: null,
};

const EXAMPLES = [{ question: "Eylül 2026'da satışlarımız ne kadar?", kind: "golden" }];

// Cümlelerdeki kesme işareti SSR çıktısında düz karakter değildir; okunur metin öyle aranır.
function render(node) {
  return renderToStaticMarkup(node)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&amp;/g, "&");
}

function cardMarkup(card, props = {}) {
  return render(<StartCard card={card} {...props} />);
}

let container;
let root;

async function mount(props = {}) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => {
    root.render(<StartScreen onChange={noop} onAsk={noop} {...props} />);
  });
  return container;
}

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

async function click(node) {
  await act(async () => {
    node.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  });
}

beforeEach(() => {
  window.location.hash = "#/";
});

afterEach(() => {
  if (root) {
    act(() => root.unmount());
    root = undefined;
  }
  container?.remove();
  container = undefined;
  window.location.hash = "#/";
  vi.clearAllMocks();
});

// "Panodan çıkar" ekranın kapısından gerçek `api.unpinCard`ı çağırır (mockta o yoktur), o yüzden
// ağ burada stub'lanır: çağrının DELETE ve kartın adresinde olduğu da böylece okunur.
const FETCH = globalThis.fetch;

function fetchResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => (body === undefined ? "" : JSON.stringify(body)),
  };
}

function stubFetch(result) {
  const calls = [];
  globalThis.fetch = vi.fn(async (path, init) => {
    calls.push({ path, init });
    return result;
  });
  return calls;
}

afterEach(() => {
  globalThis.fetch = FETCH;
});

describe("StartCard", () => {
  it("kart kendi kimliği ve yüküyle boyanır: sayı büyük, etiket altında", () => {
    const html = cardMarkup(NUMBER);
    expect(html).toContain('class="card start-card"');
    expect(html).toContain('data-card-id="11"');
    expect(html).toContain('data-display="number"');
    expect(html).toContain(">Bu ay net satış</h2>");
    expect(html).toContain('class="result-single-value start-card-value"');
    expect(html).toContain(">8.910,5<");
    expect(html).toContain(">Net satış tutarı<");
  });

  it("grafik kartı küçük ChartView, tablo kartı mini tablodur", () => {
    const chart = cardMarkup(CHART);
    expect(chart).toContain('data-display="chart"');
    expect(chart).toContain('id="chart"');

    const table = cardMarkup(TABLE);
    expect(table).toContain('data-display="table"');
    expect(table).toContain(">Ürün</th>");
    expect(table).toContain(">Siyah Çay 500 g<");
    expect(table).toContain('<td class="num">2.480</td>');
  });

  // Panonun mini tablosu da thread ile aynı okunuşu okur (M26 inceleme 1): başlık columnLabel'ın
  // döndürdüğüdür, çıplak SQL adı değil - ikisi küçük harfli adda zaten aynıdır, büyük harflide ayrılır.
  it("mini tablonun başlığı columnLabel'ın kendi çıktısıdır", () => {
    const columns = ["StockItemName", "QuantityOnHand"];
    const table = cardMarkup({ ...TABLE, columns });
    for (const name of columns) expect(table).toContain(`>${columnLabel(name)}</th>`);
    expect(cardMarkup({ ...TABLE, columns: ["STOCK_ITEM_NAME", "ADET"] })).toContain(">Stock item name</th>");
  });

  it("yenilenme yazısı ve yenile düğmesi kartta durur, zamansız kartta satır yoktur", () => {
    expect(cardMarkup(NUMBER)).toContain("5 dk önce yenilendi");
    expect(cardMarkup(NUMBER)).toContain('data-card-refresh="11"');
    expect(cardMarkup(NUMBER)).toContain(">Yenile</button>");
    expect(cardMarkup(TABLE)).not.toContain("yenilendi");
  });

  it("eksik yük ekrana undefined düşürmez: sayı yoksa –", () => {
    const html = cardMarkup({ ...NUMBER, value: null, label: null });
    expect(html).toContain(">–<");
    expect(html).not.toContain("undefined");
  });

  it("grafiği gelmeyen kart boş kutu değil, nedenini söyleyen karttır", () => {
    const html = cardMarkup({ ...CHART, chart: null });
    expect(html).toContain("Kartın grafiği yüklenemedi.");
    expect(html).not.toContain('id="chart"');
  });

  it("hata kartı err tokenlarıyladır; yeniden onay yalnız yöneticindir", () => {
    const admin = cardMarkup(BROKEN, { isAdmin: true });
    expect(admin).toContain("start-card-error error-card");
    expect(admin).toContain(">Bu giriş bu kolonu göremez.<");
    expect(admin).toContain('data-card-reapprove="14"');
    expect(admin).toContain("SQL'i yeniden onayla");

    expect(cardMarkup(BROKEN)).not.toContain("data-card-reapprove");
    expect(cardMarkup(NUMBER, { isAdmin: true })).not.toContain("data-card-reapprove");
  });

  it("kişisel kartın \"Panodan çıkar\"ı vardır; rol kartının ve kişisel olmayan kartın yoktur", () => {
    const personal = cardMarkup(TABLE);
    expect(personal).toContain('class="start-card-unpin"');
    expect(personal).toContain('data-card-unpin="13"');
    expect(personal).toContain(">Panodan çıkar</button>");

    expect(cardMarkup(NUMBER)).not.toContain("data-card-unpin");
    expect(cardMarkup({ ...NUMBER, personal: undefined })).not.toContain("data-card-unpin");
    expect(cardMarkup(BROKEN, { isAdmin: true })).not.toContain("data-card-unpin");
  });
});

describe("StartScreen", () => {
  it("kartlar GET /api/start ile gelir ve #start ızgarasında sırasıyla durur", async () => {
    api.start.mockResolvedValue({ cards: [NUMBER, TABLE] });
    const app = await mount();
    await settle();

    expect(api.start).toHaveBeenCalledTimes(1);
    const grid = app.querySelector("#start");
    expect(grid).not.toBeNull();
    expect(Array.from(grid.querySelectorAll(".start-card"), (node) => node.dataset.cardId)).toEqual([
      "11",
      "13",
    ]);
    expect(grid.querySelector(".skeleton")).toBeNull();
  });

  it("kartlar okunana kadar yerlerinde iskelet kartlar boyanır", async () => {
    api.start.mockReturnValue(new Promise(() => {})); // dönmeyen istek: kartlar henüz yolda
    const app = await mount();

    expect(app.querySelectorAll("#start .skeleton")).toHaveLength(3);
    expect(app.querySelector("#start .start-card[data-card-id]")).toBeNull();
  });

  it("karta tıklamak konuşmayı açar: POST open, ardından #/c/<id>", async () => {
    api.start.mockResolvedValue({ cards: [NUMBER] });
    api.startOpen.mockResolvedValue({ conversation_id: ID });
    const app = await mount();
    await settle();

    await click(app.querySelector(".start-card"));
    await settle();

    expect(api.startOpen).toHaveBeenCalledWith(11);
    expect(window.location.hash).toBe(`#/c/${ID}`);
  });

  it("yenile kartın yükünü yerinde değiştirir ve kartı açmaz", async () => {
    api.start.mockResolvedValue({ cards: [NUMBER] });
    api.startRefresh.mockResolvedValue({ card: { ...NUMBER, value: 100, refreshed_at: minutesAgo(0) } });
    const app = await mount();
    await settle();

    await click(app.querySelector("button[data-card-refresh]"));
    await settle();

    expect(api.startRefresh).toHaveBeenCalledWith(11);
    expect(api.startOpen).not.toHaveBeenCalled();
    expect(app.querySelector(".start-card-value").textContent).toBe("100");
    expect(app.querySelector(".start-card-meta").textContent).toBe("az önce yenilendi");
  });

  it("429'un cümlesi kartın içinde okunur, kartın yükü değişmez", async () => {
    api.start.mockResolvedValue({ cards: [NUMBER] });
    api.startRefresh.mockRejectedValue(
      new api.ApiError(429, "Bu kart az önce yenilendi; 12 sn sonra yeniden deneyin."),
    );
    const app = await mount();
    await settle();

    await click(app.querySelector("button[data-card-refresh]"));
    await settle();

    expect(app.textContent).toContain("Bu kart az önce yenilendi; 12 sn sonra yeniden deneyin.");
    expect(app.querySelector(".start-card-value").textContent).toBe("8.910,5");
    expect(app.querySelector(".start-card-refresh").disabled).toBe(false);
  });

  it("yenilemeye tıklamak kartı açmaz", async () => {
    api.start.mockResolvedValue({ cards: [NUMBER] });
    api.startRefresh.mockResolvedValue({ card: NUMBER });
    const app = await mount();
    await settle();

    await click(app.querySelector("button[data-card-refresh]"));
    await settle();

    expect(api.startOpen).not.toHaveBeenCalled();
  });

  // Yenilemenin ortası sessiz: düğme kapanıyor, yük ise yanıt gelince değişiyor. Kart o arada
  // kendi sınıfıyla meşgul olduğunu taşımalı (`start-card-refreshing` → CSS'teki bant).
  it("yenileme sürerken kartın sınıfı bunu taşır, yanıt inince düşer", async () => {
    let land;
    api.start.mockResolvedValue({ cards: [NUMBER] });
    api.startRefresh.mockReturnValue(
      new Promise((resolve) => {
        land = resolve;
      }),
    );
    const app = await mount();
    await settle();

    const card = app.querySelector('.start-card[data-card-id="11"]');
    await click(card.querySelector("button[data-card-refresh]"));

    expect(card.className).toContain("start-card-refreshing");

    land({ card: { ...NUMBER, value: 100 } });
    await settle();

    expect(card.className).not.toContain("start-card-refreshing");
  });

  it("reddedilen yenileme de kartın meşgul sınıfını bırakır", async () => {
    let refuse;
    api.start.mockResolvedValue({ cards: [NUMBER] });
    api.startRefresh.mockReturnValue(
      new Promise((_, reject) => {
        refuse = reject;
      }),
    );
    const app = await mount();
    await settle();

    const card = app.querySelector('.start-card[data-card-id="11"]');
    await click(card.querySelector("button[data-card-refresh]"));

    expect(card.className).toContain("start-card-refreshing");

    refuse(new api.ApiError(429, "Bu kart az önce yenilendi; 28 sn sonra yeniden deneyin."));
    await settle();

    expect(card.className).not.toContain("start-card-refreshing");
    expect(app.querySelector(".start-card-refresh").disabled).toBe(false);
  });

  it("yönetici hata kartında soruyu soru kutusuna alır", async () => {
    const reapproved = [];
    api.start.mockResolvedValue({ cards: [BROKEN] });
    const app = await mount({ isAdmin: true, onReapprove: (card) => reapproved.push(card) });
    await settle();

    await click(app.querySelector("button[data-card-reapprove]"));
    await settle();

    expect(reapproved.map((card) => card.id)).toEqual([14]);
    expect(api.startOpen).not.toHaveBeenCalled();
  });

  it("kart yoksa tek cümle; yönetici Hazır sorular ekranına bağlanır", async () => {
    api.start.mockResolvedValue({ cards: [] });
    const admin = await mount({ isAdmin: true });
    await settle();

    const line = admin.querySelector("#start-empty");
    expect(line.textContent).toContain("Panonda henüz kart yok");
    expect(line.querySelector('a[href="#/hazir-sorular"]').textContent).toBe("Hazır sorular");
    expect(admin.querySelector(".start-card")).toBeNull();
    await act(async () => root.unmount());
    root = undefined;
    container.remove();

    api.start.mockResolvedValue({ cards: [] });
    const user = await mount();
    await settle();
    expect(user.querySelector("#start-empty").textContent).toContain("Panonda henüz kart yok");
    expect(user.querySelector("#start-empty a")).toBeNull();
  });

  it("soru kutusu ve örnek çipler panonun altında erişilebilir kalır", async () => {
    api.start.mockResolvedValue({ cards: [NUMBER] });
    const app = await mount({ examples: EXAMPLES, text: "Kaç fatura?" });
    await settle();

    const box = app.querySelector("#question");
    expect(box.placeholder).toBe("Sorunuzu yazın");
    expect(box.value).toBe("Kaç fatura?");
    expect(app.querySelector(".example-chip").textContent).toBe(EXAMPLES[0].question);
  });

  it("kartlar okunamazsa ekran üstüne düşürülür", async () => {
    api.start.mockRejectedValue(new api.ApiError(500, "Sunucu hatası (500)."));
    const failed = [];
    const app = await mount({ onFailed: () => failed.push(1) });
    await settle();

    expect(failed).toEqual([1]);
    expect(app.querySelector("#start .start-card[data-card-id]")).toBeNull();
    expect(app.querySelector("#question")).not.toBeNull();
  });

  it("kişisel kartı panodan çıkarmak DELETE eder ve kartı yerinden düşürür", async () => {
    api.start.mockResolvedValue({ cards: [NUMBER, TABLE] });
    const calls = stubFetch(fetchResponse(200, { deleted: 13 }));
    const app = await mount();
    await settle();

    await click(app.querySelector("button[data-card-unpin]"));
    await settle();

    expect(calls[0].path).toBe("/api/start/cards/13");
    expect(calls[0].init.method).toBe("DELETE");
    expect(Array.from(app.querySelectorAll(".start-card"), (node) => node.dataset.cardId)).toEqual(["11"]);
    expect(api.start).toHaveBeenCalledTimes(1); // liste baştan okunmaz
    expect(api.startOpen).not.toHaveBeenCalled(); // konuşma açılmaz
    expect(window.location.hash).toBe("#/");
  });

  it("reddedilen çıkarma kartı yerinde bırakır ve cümlesi kartın altında okunur", async () => {
    api.start.mockResolvedValue({ cards: [TABLE] });
    stubFetch(fetchResponse(404, { detail: "Böyle bir kartın yok." }));
    const app = await mount();
    await settle();

    await click(app.querySelector("button[data-card-unpin]"));
    await settle();

    expect(app.querySelector('.start-card[data-card-id="13"]')).not.toBeNull();
    expect(app.querySelector(".start-card-note").textContent).toBe("Böyle bir kartın yok.");
    expect(app.querySelector("button[data-card-unpin]").disabled).toBe(false);
  });
});
