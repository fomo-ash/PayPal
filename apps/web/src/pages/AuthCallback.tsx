import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ErrorNote, Spinner } from "../components";
import { useAuth } from "../lib/auth";

// PayPal sends the browser here after "Log in with PayPal".
export default function AuthCallback() {
  const [params] = useSearchParams();
  const { finishPayPalLogin } = useAuth();
  const nav = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const once = useRef(false);

  useEffect(() => {
    if (once.current) return;
    once.current = true;
    const code = params.get("code");
    const state = params.get("state");
    if (!code || !state) {
      setError(params.get("error_description") || "PayPal did not send a login code.");
      return;
    }
    finishPayPalLogin(code, state)
      .then((u) => nav(u.role === "buyer" ? "/me" : "/", { replace: true }))
      .catch((e) => setError(e.message));
  }, [params, finishPayPalLogin, nav]);

  if (error) return <div className="narrow"><ErrorNote error={error} /><Link to="/login">Try again</Link></div>;
  return <Spinner label="Logging you in with PayPal" />;
}
