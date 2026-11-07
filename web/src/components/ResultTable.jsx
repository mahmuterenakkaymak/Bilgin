// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { formatCell, formatNumber, isNumericColumn } from "../lib/format.js";

// Sonuç tablosu: başlık yapışkan, sayı sütunları sağda ve Türkçe, boş hücre "–". Alt yazı yalnız
// kesik sonuçta vardır; gösterilen sayı ekrandaki satırın sayısıdır, toplam payload'dan gelir (R5-18).
const VISIBLE_ROWS = 200;

export default function ResultTable({ columns = [], rows = [], rowCount = 0, truncated = false }) {
  const names = Array.isArray(columns) ? columns : [];
  const list = Array.isArray(rows) ? rows : [];
  if (!list.length) return <p className="table-empty">Bu soruya uyan kayıt yok.</p>;

  const shown = list.slice(0, VISIBLE_ROWS);
  const numeric = names.map((_, index) => isNumericColumn(shown, index));
  const total = Number.isFinite(rowCount) && rowCount > 0 ? rowCount : list.length;

  return (
    <div className="result-block">
      <div className="table-wrap">
        <table id="result-table" className="result-table">
          <thead>
            <tr>
              {names.map((name, index) => (
                <th key={`${index}-${name}`} scope="col" className={numeric[index] ? "num" : undefined}>
                  {name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {names.map((_, index) => (
                  <td key={index} className={numeric[index] ? "num" : undefined}>
                    {formatCell(row?.[index])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {truncated && (
        <p className="table-note">
          İlk {formatNumber(shown.length)} satır gösteriliyor (toplam {formatNumber(total)}).
        </p>
      )}
    </div>
  );
}
