import { useEffect, useState } from "react";
import { STEPS, STEP_MS, stepAt } from "../lib/steps.js";

// Bekleme kartı: adım yazısı geçen süreden ilerler, sayım son adımda durur (R5-18).
// Saat bileşende durur; her soru için yeniden kurulduğu için sıfırdan başlar.
export default function LoadingSteps() {
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
        {STEPS[index]}
        <span className="loading-count">
          {index + 1} / {STEPS.length}
        </span>
      </p>
    </section>
  );
}
