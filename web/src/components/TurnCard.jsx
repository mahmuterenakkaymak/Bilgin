import { useT } from "../i18n/index.js";
import { columnLabel } from "../lib/chartFormat.js";
import { formatCell, isNumericColumn } from "../lib/format.js";
import AnswerCard from "./AnswerCard.jsx";
import ClarificationCard from "./ClarificationCard.jsx";
import ErrorCard from "./ErrorCard.jsx";
import LoadingSteps from "./LoadingSteps.jsx";

// Katlanmış turun tablosu en çok bu kadar satır gösterir: kayıtlı turda depoda da bu kadar durur
// (Contracts "TurnSummary"), böylece katlanmış tur canlıyken de kayıtlıyken de aynı görünür.
const COLLAPSED_ROWS = 5;

// Tur kartı: akıştaki bir turun cevabı. Son tur (ya da açılmış olan) tam karttır; eskiler cümle ve
// saklanan satırlardır, tıklayınca açılır. Kayıtlı turda yük yoktur — tam tablo ve grafik ancak
// SQL yeniden koşularak elde edilir, o yüzden açmak hiçbir şey koşturmaz (R7-15).
// `onExpand(tur no)` aç/kapatı çevirir, `onReplay(tur)` kayıtlı SQL'i yeniden koşar.
// `isLast` akışın son turu: son tur hiç katlanmaz (thread.js `mark`), o yüzden kapanacak bir katı
// yoktur ve Kapat düğmesi açılmaz (M23 review 3).
// `isAdmin` ve `reapproveId` cevabın panonun diliyle konuşması içindir (R7-21): kartı yalnız canlı
// tur açar, kayıtlı turda yürüyecek bir yük yoktur.
export default function TurnCard({ turn, onExpand, onReplay, onChoose, onChange, onSave, isAdmin = false, reapproveId = null, isLast = false }) {
  const { lang } = useT();
  const summary = turn?.summary ?? {};
  const columns = Array.isArray(summary.columns) ? summary.columns : [];
  const rows = Array.isArray(summary.rows) ? summary.rows : [];
  const payload = turn?.payload ?? null;
  const collapsed = Boolean(turn?.collapsed);
  // Kayıtlı bir başarısız turda cümle boş gelebilir; indirgeyicinin düştüğü cümle burada da okunur.
  const sentence =
    (typeof turn?.answer_text === "string" ? turn.answer_text.trim() : "") ||
    (turn?.status === "failed" ? "Cevap üretilemedi." : "");
  const replayable = Boolean(turn?.stored && turn?.audit_id && onReplay);

  // Bekleyen turun cevabı henüz yok; tam kart "Cevaplandı" yazacağı için bekleme kartı açılır.
  if (turn?.pending || turn?.status === "loading") return <LoadingSteps />;

  if (!collapsed) {
    // Cevaplanmamış tur tam kartın yerine kendi kartını koyar: AnswerCard'ın durum satırı yalan olur.
    if (summary.clarification) {
      return (
        <ClarificationCard
          payload={payload ?? { clarification: summary.clarification }}
          onChoose={onChoose}
          onChange={onChange}
        />
      );
    }
    if (payload && turn?.status === "answered") {
      return (
        <AnswerCard
          payload={payload}
          choice={turn?.choice}
          onSave={onSave}
          isAdmin={isAdmin}
          reapproveId={reapproveId}
        />
      );
    }
    if (payload) return <ErrorCard kind={payload?.error?.kind} message={sentence} />;
  }

  const shown = collapsed ? rows.slice(0, COLLAPSED_ROWS) : rows;
  const numeric = columns.map((_, index) => isNumericColumn(shown, index));
  // Yalnız katlanmış kart tıklamayla açılır; açılmış kartın kapanma düğmesi aşağıda durur.
  const open = () => onExpand?.(turn?.n);

  return (
    <div
      className="turn-collapsed"
      role={collapsed ? "button" : undefined}
      tabIndex={collapsed ? 0 : undefined}
      aria-expanded={collapsed ? false : undefined}
      onClick={collapsed ? open : undefined}
      onKeyDown={
        collapsed
          ? (event) => {
              if (event.key !== "Enter" && event.key !== " ") return;
              event.preventDefault();
              open();
            }
          : undefined
      }
    >
      {sentence && <p className="turn-sentence">{sentence}</p>}
      {columns.length > 0 && shown.length > 0 && (
        <div className="turn-table-wrap">
          <table className="turn-table">
            <thead>
              <tr>
                {columns.map((name, index) => (
                  <th key={`${index}-${name}`} scope="col" className={numeric[index] ? "num" : undefined}>
                    {columnLabel(name)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {columns.map((_, index) => (
                    <td key={index} className={numeric[index] ? "num" : undefined}>
                      {formatCell(row?.[index], lang)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {replayable && (
        <div className="turn-actions">
          <p className="turn-note">Tam tablo ve grafik için yeniden çalıştırın.</p>
          <button
            type="button"
            className="btn"
            data-turn-replay={turn.n}
            onClick={(event) => {
              // Düğme kartın kendi tıklaması olmasın: yeniden koşarken tur açılıp kapanmasın.
              event.stopPropagation();
              onReplay(turn);
            }}
          >
            Yeniden çalıştır
          </button>
        </div>
      )}
      {!collapsed && !isLast && (
        <button type="button" className="btn btn-ghost turn-close" onClick={open}>
          Kapat
        </button>
      )}
    </div>
  );
}
