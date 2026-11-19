import { FormEvent, useState } from "react";
import { api, Me } from "../api";
import Icon from "../components/Icon";

export default function Login({ onIn }: { onIn: (m: Me) => void }) {
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try { onIn(await api.post<Me>("/api/login", { username: u, password: p })); }
    catch (x) { setErr((x as Error).message); }
    finally { setBusy(false); }
  };
  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="brand big"><span className="logo-mark"><Icon name="helmet" color="#fff" stroke={1.8} /></span>IRATEC<span style={{ fontWeight: 500, color: "#5E6878" }}>.attendance</span></div>
        <p className="muted">Sign in with your account.</p>
        <label>Username<input value={u} onChange={(e) => setU(e.target.value)} autoFocus autoComplete="username" required /></label>
        <label>Password<input type="password" value={p} onChange={(e) => setP(e.target.value)} autoComplete="current-password" required /></label>
        {err && <div className="form-err">{err}</div>}
        <button className="btn primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
    </div>
  );
}
