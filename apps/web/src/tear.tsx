import { useEffect, useState, type CSSProperties } from "react";
import { usd } from "./lib/format";

export interface Split {
  amount: number;   // the hold
  worker: number;
  fee: number;
  back: number;     // released to the buyer, never charged
}

const reduced = () => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** The hold bar. At t=0 it is one piece; at t=1 the three parts have torn apart at the cents.
 *  `t` may be driven by scroll (Home) or by `torn` (verdict page, animated once by CSS). */
export function Tear({ split, t, torn, isVoid, whole, label, state }: {
  split: Split; t?: number; torn?: boolean; isVoid?: boolean; whole?: boolean; label?: string; state?: string;
}) {
  const pct = (v: number) => `${Math.max(0, (v / (split.amount || 1)) * 100)}%`;
  const style = { "--t": t !== undefined ? t.toFixed(3) : torn ? 1 : 0 } as CSSProperties;
  const aria = whole
    ? `${usd(split.amount)} held, not yet settled.`
    : isVoid
    ? `Voided. ${usd(split.amount)} back to the buyer.`
    : `Of ${usd(split.amount)} held: ${usd(split.worker)} to the worker, ${usd(split.fee)} fee, ${usd(split.back)} released to the buyer.`;
  return (
    <div className={`tear ${isVoid ? "is-void" : ""} ${t === undefined ? "is-timed" : ""}`} style={style}>
      {(label || state) && (
        <div className="tear__label mono"><span>{label}</span><span>{state}</span></div>
      )}
      <div className="tear__bar" role="img" aria-label={aria}>
        {whole ? (
          <div className="piece piece--whole" style={{ flex: "1 1 0" }}>
            <div className="piece__fill" />
            <div className="piece__amt num">{usd(split.amount)} held</div>
          </div>
        ) : isVoid ? (
          <div className="tear__void"><span>Voided</span><span className="num">{usd(split.amount)} back to the buyer</span></div>
        ) : (
          <>
            {split.worker > 0 && (
              <div className="piece piece--worker" style={{ flex: `0 0 ${pct(split.worker)}`, "--dx": "-18px", "--dy": "46px", "--rot": "-1deg", "--ox": "100%" } as CSSProperties}>
                <div className="piece__fill" />
                <div className="piece__amt num">{usd(split.worker)}</div>
                <div className="piece__dest"><b>To the worker</b><span>PayPal payout</span></div>
              </div>
            )}
            {split.fee > 0 && (
              <div className="piece piece--fee" style={{ flex: `0 0 ${pct(split.fee)}`, "--dx": "0px", "--dy": "-38px", "--rot": "0deg" } as CSSProperties}>
                <div className="piece__fill" />
                <div className="piece__dest piece__dest--up"><b>Fee <span className="num">{usd(split.fee)}</span></b></div>
              </div>
            )}
            {split.back > 0 && (
              <div className="piece piece--back" style={{ flex: "1 1 0", "--dx": "22px", "--dy": "46px", "--rot": "1.6deg", "--ox": "0%" } as CSSProperties}>
                <div className="piece__fill" />
                <div className="piece__amt num">{usd(split.back)}</div>
                <div className="piece__dest piece__dest--end"><b>Never charged</b><span>released to the buyer</span></div>
              </div>
            )}
          </>
        )}
      </div>
      {!isVoid && (
        <ul className={`tear__legend ${whole ? "is-hidden" : ""}`}>
          <li><span><i className="sw sw--worker" />To the worker</span><b className="num">{usd(split.worker)}</b></li>
          <li><span><i className="sw sw--fee" />Fee</span><b className="num">{usd(split.fee)}</b></li>
          <li><span><i className="sw sw--back" />Back to the buyer</span><b className="num">{usd(split.back)}</b></li>
        </ul>
      )}
    </div>
  );
}

/** true after `delay` ms, once `ready` is true; immediately when motion is reduced. */
export function useOnceAfter(ready: boolean, delay = 450): boolean {
  const [on, setOn] = useState(false);
  useEffect(() => {
    if (!ready || on) return;
    if (reduced()) { setOn(true); return; }
    const id = window.setTimeout(() => setOn(true), delay);
    return () => window.clearTimeout(id);
  }, [ready, on, delay]);
  return on;
}

/** Counts from 0 up to `to` once `start` is true (final value at once when motion is reduced). */
export function useCount(to: number, start: boolean, ms = 900): number {
  const [v, setV] = useState(0);
  useEffect(() => {
    if (!start) return;
    if (reduced()) { setV(to); return; }
    let raf = 0;
    const t0 = performance.now();
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / ms);
      setV(Math.round(to * (1 - Math.pow(1 - k, 3))));
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [to, start, ms]);
  return v;
}
