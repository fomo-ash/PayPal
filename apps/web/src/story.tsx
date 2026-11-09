import "./vendor/scrollcraft.css";
import "./vendor/scrollcraft.js";

import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Tear } from "./tear";

declare global {
  interface Window { ScrollCraft?: { mount: (root: Element) => { destroy: () => void } } }
}

// A real run on the hosted API (Render + PayPal sandbox): the honest_partial submission.
const RUN = { fresh: 188, freshTotal: 200, score: "75.1%", split: { amount: 100, worker: 71.39, fee: 3.76, back: 24.85 } };

const STEPS = [
  { key: "hold", title: "Hold", body: "The buyer approves $100.00 in PayPal. It is an authorization: held on their account, not charged." },
  { key: "test", title: "Test", body: "The code runs in an isolated sandbox on the hidden tests and on fresh inputs nobody has seen. Expected answers never go in." },
  { key: "judge", title: "Judge", body: "An AI reads the code for cheating and cites lines. It cannot raise a payment, and a flag only sends the case to a person." },
  { key: "settle", title: "Settle", body: "PayPal captures exactly the share that passed, pays the worker, and releases the rest. Nothing is refunded because it was never taken." },
  { key: "proof", title: "Proof", body: "A receipt signed with Ed25519 records the PayPal IDs and the scores. Anyone can check it." },
];
const STATUS = ["HELD", "TESTING", "JUDGED", "SETTLED", "SIGNED"];

const reducedMotion = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Home's one told story: a pinned act; the same hold card fills in, line by line, as you scroll. */
export function HoldStory() {
  const root = useRef<HTMLDivElement>(null);
  const act = useRef<HTMLElement>(null);
  const [step, setStep] = useState(0);
  const [t, setT] = useState(0);
  const [meter, setMeter] = useState(0);

  useEffect(() => {
    if (reducedMotion()) { setStep(4); setT(1); setMeter(1); return; }
    const api = root.current && window.ScrollCraft ? window.ScrollCraft.mount(root.current) : null;
    let raf = 0;
    let last = -1;
    const frame = () => {
      const el = act.current;
      const p = el ? parseFloat(el.style.getPropertyValue("--sc-p")) || 0 : 0;
      if (Math.abs(p - last) > 0.001) {
        last = p;
        const s = Math.min(4, Math.floor(p * 5.2));
        setStep(s);
        setMeter(Math.min(1, Math.max(0, (p - 0.2) / 0.14)));
        // the tear owns the 4th fifth of the act, with a short silence before it starts
        setT(1 - Math.pow(1 - Math.min(1, Math.max(0, (p - 0.62) / 0.16)), 3));
      }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => { cancelAnimationFrame(raf); api?.destroy(); };
  }, []);

  return (
    <div ref={root} className="story-root">
      <section ref={act} className="story" data-sc-act="pin" data-sc-span="3.4" aria-labelledby="story-h">
        <div data-sc-stage className="story__stage">
          <div className="story__grid">
            <div className="story__copy">
              <h2 id="story-h" className="story__h">One hold, five states.</h2>
              <ol className="story__steps">
                {STEPS.map((s, i) => (
                  <li key={s.key} className={i === step ? "is-now" : i < step ? "is-done" : ""} aria-current={i === step ? "step" : undefined}>
                    <b>{s.title}</b>
                    <p>{s.body}</p>
                  </li>
                ))}
              </ol>
            </div>

            <article className="ledger" aria-label="A real job, from the hosted sandbox">
              <header className="ledger__head">
                <div>
                  <p className="ledger__kicker mono">PayPal authorization</p>
                  <p className="ledger__amt num">$100.00</p>
                </div>
                <span className={`ledger__status mono s-${step}`}>{STATUS[step]}</span>
              </header>

              <ul className="ledger__lines">
                <li className="is-in">
                  <span>Held on the buyer's PayPal</span><span className="num">$100.00</span>
                </li>
                <li className={step >= 1 ? "is-in" : ""}>
                  <span>Fresh inputs passed</span>
                  <span className="num">{Math.round(RUN.fresh * meter)}/{RUN.freshTotal}</span>
                  <i className="ledger__meter" style={{ transform: `scaleX(${(RUN.fresh / RUN.freshTotal) * meter})` }} aria-hidden="true" />
                </li>
                <li className={step >= 1 ? "is-in" : ""}>
                  <span>Score, lower of hidden and fresh per group</span><span className="num">{RUN.score}</span>
                </li>
                <li className={step >= 2 ? "is-in" : ""}>
                  <span>AI review: clear. Notes a skipped rule at <span className="mono">solution.py:6</span>, not cheating</span>
                  <span className="ledger__ok mono">clear</span>
                </li>
              </ul>

              <div className={`ledger__tear ${step >= 3 ? "is-in" : ""}`}>
                <Tear split={RUN.split} t={t} whole={step < 3} />
              </div>

              <footer className={`ledger__foot ${step >= 4 ? "is-in" : ""}`}>
                <span className="mono">Receipt · Ed25519 · signed</span>
                <Link to="/verify">Verify one →</Link>
              </footer>
            </article>
          </div>
        </div>
      </section>
    </div>
  );
}
