import { formatCell, formatNumber, isNumericColumn } from "../lib/format.js";

// Sonuç tablosu: başlık yapışkan, sayı sütunları sağda ve Türkçe, boş hücre "–". Alt yazı yalnız
// kesik sonuçta vardır; gösterilen sayı ekrandaki satırın sayısıdır, toplam payload'dan gelir (R5-18).
const VISIBLE_ROWS = 200;

export default function ResultTable({ columns = [], rows = [], rowCount = 0, truncated = false }) {
  const names = Array.isArray(columns) ? columns : [];
  const list = Array.isArray(rows) ? rows : [];
  if (!list.length) return <p className="table-empty">Bu soruya uyan kayıt yok.</p>;

  const shown = list.slice(0, VISIBLE_ROWS);
  const total = Number.isFinite(rowCount) && rowCount > 0 ? rowCount : list.length;
  const note = truncated && (
    <p className="table-note">
      İlk {formatNumber(shown.length)} satır gösteriliyor (toplam {formatNumber(total)}).
    </p>
  );

  // Tek kolon ve tek satır bir sayıdır, tablo değil: .result-table width:100% olduğu için tek
  // hücre boş kutunun ucuna yaslanıyordu. Başka her biçim (tek kolon iki satır, tek satır iki
  // kolon) tablo olarak kalır.
  if (names.length === 1 && list.length === 1) {
    return (
      <div className="result-block">
        <div id="result-single" className="result-single">
          <span className="result-single-label">{names[0]}</span>
          <span className="result-single-value">{formatCell(list[0]?.[0])}</span>
        </div>
        {note}
      </div>
    );
  }

  const numeric = names.map((_, index) => isNumericColumn(shown, index));

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
      {note}
    </div>
  );
}
