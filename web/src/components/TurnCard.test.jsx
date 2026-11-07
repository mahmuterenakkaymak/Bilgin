// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

// Akışın iki görünümü tek adlandırmayı okumalı (M25 review 1): katlanmış turun başlık satırı
// `SEHIR_SAYISI` yazıp hemen altında açılmış kart `Sehir sayisi` yazıyordu. Kartın tek etiketi
// chartFormat.columnLabel'dır; katlanmış başlık da aynı işlevi okur.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import TurnCard from "./TurnCard.jsx";

const noop = () => {};

const COLUMNS = ["SEHIR_SAYISI", "CountryName", "Ürün_ADI"];
const ROWS = [[12, "Türkiye", "Çay"], [7, "Türkiye", "Kahve"]];

// Depodan gelen tur: özet saklandığı kadardır, yük hiç yoktur; açmak hiçbir şey koşturmaz (R7-15).
function turn(collapsed) {
  return {
    n: 1,
    question: "Şehre göre ürün sayısı kaç?",
    choice: null,
    status: "answered",
    sql: "SELECT SEHIR_SAYISI, CountryName, Ürün_ADI FROM STOK",
    answer_text: "Şehirlere göre ürün sayısı.",
    audit_id: "aa1",
    created_at: "2026-10-20T09:00:00+00:00",
    stored: true,
    collapsed,
    summary: {
      columns: COLUMNS,
      row_count: 2,
      rows: ROWS,
      facts: [],
      chart_kind: null,
      context: null,
      clarification: null,
    },
  };
}

// <th> satırı sırasıyla okunur: iki görünümün aynı üç stringi yazdığı böyle ölçülür.
function headers(collapsed) {
  const html = renderToStaticMarkup(
    <TurnCard
      turn={turn(collapsed)}
      onExpand={noop}
      onReplay={noop}
      onChoose={noop}
      onChange={noop}
      onSave={noop}
    />,
  );
  const head = html.split("<thead>")[1].split("</thead>")[0];
  return [...head.matchAll(/<th[^>]*>(.*?)<\/th>/g)].map((match) => match[1]);
}

describe("katlanmış turun tablo başlığı", () => {
  it("büyük harfli alias kelimeye döner, elle yazılmış alias olduğu gibi kalır", () => {
    // ASSUMPTION: columnLabel içinde küçük harf taşıyan alias'ı yeniden yazmaz (T379), o yüzden
    // `Ürün_ADI` katlanmış başlıkta da kartta da tıpatıp aynı okunur; düzeltilen iki görünümün ayrılığıdır.
    expect(headers(true)).toEqual(["Sehir sayisi", "CountryName", "Ürün_ADI"]);
  });

  it("açılmış turun kartıyla katlanmış turun başlığı aynı üç etiketi yazar", () => {
    expect(headers(false)).toEqual(["Sehir sayisi", "CountryName", "Ürün_ADI"]);
    expect(headers(false)).toEqual(headers(true));
  });
});
