import { useEffect, useRef, type ReactNode } from "react";
import { Link, NavLink, useNavigate } from "react-router-dom";
import { useAuth } from "./lib/auth";
import { STATE_LABEL, tone } from "./lib/format";
import type { Finding } from "./lib/types";

export function Mark() {
  return (
    <Link to="/" className="mark" aria-label="Verdict home">
      <svg viewBox="0 0 32 32" aria-hidden="true">
        <rect width="32" height="32" rx="8" fill="#111" />
        <path d="M9 16.5l4.5 4.5L23 11" stroke="#F6F5F1" strokeWidth="3" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      Verdict
    </Link>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const { user, config, logout } = useAuth();
  const nav = useNavigate();
  return (
    <>
      <BackdropVideo />
      <header className="top">
        <Mark />
        <nav className="top__nav" aria-label="Main">
          <NavLink to="/" end>Jobs</NavLink>
          {user?.role === "buyer" && <NavLink to="/jobs/new">Post a job</NavLink>}
          {user && user.role !== "admin" && <NavLink to="/me">{user.role === "buyer" ? "My jobs" : "My work"}</NavLink>}
          {user?.role === "admin" && <NavLink to="/review">Review queue</NavLink>}
          <NavLink to="/verify">Verify a receipt</NavLink>
        </nav>
        <div className="top__who">
          {config && config.paypal_env !== "live" && <span className="tag tag--sandbox">PayPal sandbox</span>}
          {user ? (
            <>
              <span className="who">
                <span className={`role role--${user.role}`}>{user.role === "admin" ? "reviewer" : user.role}</span>
                <span className="who__name">{user.display_name}</span>
              </span>
              <button className="btn btn--ghost btn--sm" onClick={() => { logout(); nav("/"); }}>Log out</button>
            </>
          ) : (
            <Link className="btn btn--sm" to="/login">Log in</Link>
          )}
        </div>
      </header>
      <main className="page">{children}</main>
      <footer className="foot">
        <span>PayPal holds the money. Verdict checks the code. The AI can never raise a payment.</span>
        <a href="https://github.com/fomo-ash/PayPal">Source</a>
      </footer>
    </>
  );
}

// A slow card tap behind every page, washed in cream so text stays readable.
// Still poster only when the visitor asks for less motion.
function BackdropVideo() {
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    v.muted = true;
    const still = matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => (still.matches ? v.pause() : v.play().catch(() => {}));
    apply();
    still.addEventListener("change", apply);
    return () => still.removeEventListener("change", apply);
  }, []);
  return (
    <div className="backdrop" aria-hidden="true">
      <video ref={ref} muted loop playsInline preload="auto" poster="/bg/pay.jpg">
        <source src="/bg/pay.webm" type="video/webm" />
        <source src="/bg/pay.mp4" type="video/mp4" />
      </video>
    </div>
  );
}

export function StatePill({ state }: { state: string }) {
  return <span className={`pill pill--${tone(state)}`}>{STATE_LABEL[state] ?? state}</span>;
}

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return <p className="note note--err" role="alert">{error}</p>;
}

export function Spinner({ label }: { label: string }) {
  return (
    <p className="spin" role="status">
      <span className="spin__dot" aria-hidden="true" />
      {label}
    </p>
  );
}

// Source with line numbers; lines an AI or scanner finding points at are marked.
export function CodeView({ files, findings }: { files: Record<string, string>; findings: Finding[] }) {
  const first = useRef<HTMLDivElement>(null);
  useEffect(() => {
    first.current?.scrollIntoView({ block: "center" });
  }, [files]);
  let marked = false;
  return (
    <div className="code">
      {Object.entries(files).map(([path, src]) => {
        const hits = new Map<number, Finding[]>();
        for (const f of findings) if (f.file === path) hits.set(f.line, [...(hits.get(f.line) ?? []), f]);
        return (
          <section key={path} className="code__file">
            <h4 className="code__path mono">{path}</h4>
            <div className="code__body" role="region" aria-label={`Source of ${path}`} tabIndex={0}>
              {src.split("\n").map((line, i) => {
                const n = i + 1;
                const hit = hits.get(n);
                const isFirst = !!hit && !marked;
                if (hit) marked = true;
                return (
                  <div key={n} ref={isFirst ? first : undefined} className={`code__line ${hit ? "is-hit" : ""}`}>
                    <span className="code__n">{n}</span>
                    <span className="code__src">{line || " "}</span>
                    {hit && <span className="code__why">{hit.map((h) => h.category || "flag").join(", ")}</span>}
                  </div>
                );
              })}
            </div>
          </section>
        );
      })}
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="field">
      <span className="field__label">{label}</span>
      {children}
      {hint && <span className="field__hint">{hint}</span>}
    </label>
  );
}

export function NeedRole({ role, children }: { role: "buyer" | "worker" | "admin"; children: ReactNode }) {
  const { user, ready } = useAuth();
  if (!ready) return <Spinner label="Loading" />;
  if (!user || user.role !== role) {
    return (
      <div className="empty">
        <h2>Log in as a {role === "admin" ? "reviewer" : role} to see this</h2>
        <Link className="btn" to={`/login?as=${role}`}>Log in</Link>
      </div>
    );
  }
  return <>{children}</>;
}
