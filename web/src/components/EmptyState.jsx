// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { useT } from "../i18n/index.js";

// Hiç soru sorulmamış ekranın açılışı: iki cümle ve örnek çipler (R5-18).
// ASSUMPTION: boş durumdayken çipler burada, soru sorulduktan sonra AskBox'ın altında durur;
// aynı çip iki kez görünmesin diye kutu boş durumdayken kendi çip sırasını vermez.
// Çip yoksa kutu başlık ve tek cümlenin altında boş bir alanla kalmasın: durum söylenir ve
// yönetici, kümenin açığını kapattığı tek ekrana, İş kuralları'na bağlanır (`rulesHint`).
// ASSUMPTION: ad geldiğinde lead'in kendisi onun cümlesidir; iki cümle üst üste binmesin (M22: tek
// cümle, yeni veri yok). Ad yoksa — sağlık çıktısı henüz gelmediyse — ekran bugünkü cümlesiyle açılır.
export default function EmptyState({ examples = [], rulesHint = false, datasetName = "", onSelect }) {
  const { t } = useT();
  return (
    <section className="card empty-state">
      <h1 className="screen-title">{t("empty.title")}</h1>
      <p className="screen-lead">
        {datasetName ? t("empty.leadDataset", { name: datasetName }) : t("empty.lead")}
      </p>
      {examples.length > 0 ? (
        <div className="examples">
          {examples.map((example, index) => (
            <button
              type="button"
              key={`${index}-${example?.question ?? ""}`}
              className="example-chip"
              title={example?.question ?? ""}
              onClick={() => onSelect(example?.question)}
            >
              {example?.question}
            </button>
          ))}
        </div>
      ) : (
        <p className="empty-hint" id="empty-hint">
          {t("empty.hint")}
          {rulesHint && (
            <>
              {" "}
              {t("empty.rulesBefore")}{" "}
              <a href="#/kurallar">{t("empty.rulesLink")}</a>{" "}
              {t("empty.rulesAfter")}
            </>
          )}
        </p>
      )}
    </section>
  );
}
