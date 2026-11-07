// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Mahmut Eren Akkaymak

import { useEffect, useState } from "react";
import { useT } from "../i18n/index.js";
import { STEP_KEYS, STEP_MS, stepAt } from "../lib/steps.js";

// Bekleme kartı: adım yazısı geçen süreden ilerler, sayım son adımda durur (R5-18).
// Saat bileşende durur; her soru için yeniden kurulduğu için sıfırdan başlar.
export default function LoadingSteps() {
  const { t } = useT();
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(() => setElapsed(Date.now() - started), STEP_MS);
    return () => clearInterval(timer);
  }, []);

  const index = stepAt(elapsed);

  return (
    <section id="loading" className="card loading" role="status" aria-live="polite">
      <div className="skeleton" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <p className="loading-step">
        {t(STEP_KEYS[index])}
        <span className="loading-count">
          {index + 1} / {STEP_KEYS.length}
        </span>
      </p>
    </section>
  );
}
