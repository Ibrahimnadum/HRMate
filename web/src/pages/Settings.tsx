import Icon from "../components/Icon";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api, Department, Device, qs, Settings } from "../api";
import { can, useMe } from "../App";
import { Empty, Modal, Pager, Pill, Spinner, useToast } from "../components/ui";
import { ago, WEEKDAYS } from "../util";

export default function SettingsPage() {
  const me = useMe();
  const tabs = [
    { to: "rules", label: "Board windows & work hours", show: true },
    { to: "departments", label: "Departments", show: true },
    { to: "accounts", label: "Accounts", show: can(me, "admin") },
    { to: "audit", label: "Audit log", show: can(me, "admin") },
    { to: "password", label: "My password", show: true },
  ].filter((t) => t.show);
  return (
    <div className="page">
      <header className="page-head"><div><h1 className="with-ic"><span className="title-ic"><Icon name="cog" size={22} /></span>Settings</h1></div></header>
      <nav className="tabs">{tabs.map((t) => <NavLink key={t.to} to={t.to} className={({ isActive }) => (isActive ? "on" : "")}>{t.label}</NavLink>)}</nav>
      <Routes>
        <Route index element={<Navigate to="rules" replace />} />
        <Route path="rules" element={<Rules />} />
        <Route path="departments" element={<Departments />} />
        <Route path="accounts" element={<Accounts />} />
        <Route path="audit" element={<Audit />} />
        <Route path="password" element={<Password />} />
      </Routes>
    </div>
  );
}

function Rules() {
  const me = useMe();
  const admin = can(me, "admin");
  const toast = useToast();
  const qc = useQueryClient();
  const s = useQuery({ queryKey: ["settings"], queryFn: () => api.get<Settings>("/api/settings") });
  const devs = useQuery({ queryKey: ["devices"], queryFn: () => api.get<{ rows: Device[] }>("/api/devices") });
  const [f, setF] = useState<Settings | null>(null);
  useEffect(() => { if (s.data && !f) setF(s.data); }, [s.data, f]);
  const save = useMutation({
    mutationFn: () => api.put("/api/settings", f),
    onSuccess: () => { toast("Settings saved"); qc.invalidateQueries({ queryKey: ["settings"] }); },
    onError: (e) => toast((e as Error).message, "error"),
  });
  if (!f) return <Spinner />;
  const win = (i: number, j: 0 | 1, v: string) => setF({ ...f, quiet_windows: f.quiet_windows.map((w, k) => (k === i ? (j === 0 ? [v, w[1]] : [w[0], v]) : w)) as [string, string][] });
  return (
    <div className="grid-2 top">
      <section className="card">
        <div className="card-head"><h2>Activity Board windows</h2>{s.data?.quiet_now ? <Pill tone="quiet">active until {s.data.quiet_now}</Pill> : <Pill tone="up">not active now</Pill>}</div>
        <p className="muted">During these times the service makes no connection to the devices, so the Activity Board has them to itself. Punches made inside a window are collected by the first pull after it. A window may cross midnight.</p>
        <TimelineBar windows={f.quiet_windows} />
        <div className="win-list">
          {f.quiet_windows.map((w, i) => (
            <div key={i} className="win-row">
              <input type="time" value={w[0]} disabled={!admin} onChange={(e) => win(i, 0, e.target.value)} />
              <span className="muted">to</span>
              <input type="time" value={w[1]} disabled={!admin} onChange={(e) => win(i, 1, e.target.value)} />
              {admin && <button className="link danger" onClick={() => setF({ ...f, quiet_windows: f.quiet_windows.filter((_, k) => k !== i) })}>Remove</button>}
            </div>
          ))}
          {admin && <button className="btn sm ghost" onClick={() => setF({ ...f, quiet_windows: [...f.quiet_windows, ["12:00", "13:00"]] })}>+ Add window</button>}
        </div>
      </section>
      <section className="card">
        <div className="card-head"><h2>Work hours</h2></div>
        <p className="muted">Used for the Late and Left-early flags in Excel. Shifts per department and night shifts come in Phase 3.</p>
        <div className="form two">
          <label>Work starts<input type="time" value={f.work_start} disabled={!admin} onChange={(e) => setF({ ...f, work_start: e.target.value })} /></label>
          <label>Work ends<input type="time" value={f.work_end} disabled={!admin} onChange={(e) => setF({ ...f, work_end: e.target.value })} /></label>
          <label>Grace (minutes)<input type="number" min={0} max={240} value={f.grace_minutes} disabled={!admin} onChange={(e) => setF({ ...f, grace_minutes: +e.target.value })} /></label>
          <div className="span2"><span className="ms-label">Weekend</span>
            <div className="chips tight">{WEEKDAYS.map((d, i) => { const on = f.weekend.includes(i); return <button key={d} disabled={!admin} className={`chip ${on ? "on" : ""}`} onClick={() => setF({ ...f, weekend: on ? f.weekend.filter((x) => x !== i) : [...f.weekend, i] })}>{d}</button>; })}</div></div>
        </div>
      </section>
      <section className="card">
        <div className="card-head"><h2>Devices: enrollment and nightly work</h2></div>
        <div className="form two">
          <label className="span2">Enrollment device (where HR enrolls new employees; default source for copies)
            <select value={f.enroll_device_id ?? ""} disabled={!admin} onChange={(e) => setF({ ...f, enroll_device_id: e.target.value ? +e.target.value : null })}>
              <option value="">Not set</option>{devs.data?.rows.filter((d) => !d.retired).map((d) => <option key={d.id} value={d.id}>{d.name} ({d.ip})</option>)}</select></label>
          <label>Nightly maintenance at<input type="time" value={f.maintenance_time} disabled={!admin} onChange={(e) => setF({ ...f, maintenance_time: e.target.value })} /></label>
          <label className="check-row"><input type="checkbox" checked={f.clock_sync} disabled={!admin} onChange={(e) => setF({ ...f, clock_sync: e.target.checked })} /> Set device clocks every night</label>
          <p className="muted span2" style={{ margin: 0 }}>Every night the users and fingerprints on all devices are read and backed up in this system. Must be outside the board windows.</p>
        </div>
      </section>
      {admin && <div className="span-all save-bar"><button className="btn ghost" onClick={() => setF(s.data!)}>Undo changes</button><button className="btn primary" disabled={save.isPending} onClick={() => save.mutate()}>Save settings</button></div>}
    </div>
  );
}

function TimelineBar({ windows }: { windows: [string, string][] }) {
  const m = (t: string) => { const [h, mm] = t.split(":").map(Number); return h * 60 + mm; };
  const segs: [number, number][] = [];
  windows.forEach(([a, b]) => { const s = m(a), e = m(b); if (s <= e) segs.push([s, e]); else { segs.push([s, 1440]); segs.push([0, e]); } });
  const now = new Date(); const n = now.getHours() * 60 + now.getMinutes();
  return (
    <div className="timeline">
      {segs.map(([s, e], i) => <i key={i} style={{ left: `${(s / 1440) * 100}%`, width: `${((e - s) / 1440) * 100}%` }} />)}
      <b style={{ left: `${(n / 1440) * 100}%` }} title="now" />
      <div className="tl-labels">{[0, 3, 6, 9, 12, 15, 18, 21, 24].map((h) => <span key={h} style={{ left: `${(h / 24) * 100}%` }}>{String(h).padStart(2, "0")}</span>)}</div>
    </div>
  );
}

function Departments() {
  const me = useMe();
  const edit = can(me, "admin", "hr");
  const toast = useToast();
  const qc = useQueryClient();
  const deps = useQuery({ queryKey: ["departments"], queryFn: () => api.get<{ rows: Department[] }>("/api/departments") });
  const [name, setName] = useState("");
  const done = (msg: string) => { toast(msg); qc.invalidateQueries({ queryKey: ["departments"] }); qc.invalidateQueries({ queryKey: ["employees"] }); };
  const err = (e: unknown) => toast((e as Error).message, "error");
  const add = useMutation({ mutationFn: () => api.post("/api/departments", { name }), onSuccess: () => { setName(""); done("Department added"); }, onError: err });
  const ren = useMutation({ mutationFn: (x: { id: number; name: string }) => api.patch(`/api/departments/${x.id}`, { name: x.name }), onSuccess: () => done("Renamed"), onError: err });
  const del = useMutation({ mutationFn: (id: number) => api.del(`/api/departments/${id}`), onSuccess: () => done("Deleted"), onError: err });
  return (
    <section className="card narrow-card">
      <table className="tbl"><thead><tr><th>Department</th><th className="r">Active employees</th><th /></tr></thead>
        <tbody>{deps.data?.rows.map((d) => (
          <tr key={d.id}><td><b>{d.name}</b></td><td className="r">{d.employees}</td>
            <td className="r nowrap">{edit && <><button className="link" onClick={() => { const n = prompt("New name", d.name); if (n && n !== d.name) ren.mutate({ id: d.id, name: n }); }}>Rename</button>
              {can(me, "admin") && <button className="link danger" onClick={() => confirm(`Delete ${d.name}? Its ${d.employees} employees will have no department.`) && del.mutate(d.id)}>Delete</button>}</>}</td></tr>))}
        </tbody></table>
      {edit && <div className="inline-add"><input placeholder="New department name" value={name} onChange={(e) => setName(e.target.value)} /><button className="btn primary" disabled={!name.trim()} onClick={() => add.mutate()}>Add</button></div>}
    </section>
  );
}

interface Account { username: string; role: string; display_name: string; locked_until: string | null; last_login: string | null }
function Accounts() {
  const me = useMe();
  const toast = useToast();
  const qc = useQueryClient();
  const accs = useQuery({ queryKey: ["accounts"], queryFn: () => api.get<{ rows: Account[] }>("/api/accounts") });
  const [adding, setAdding] = useState(false);
  const [f, setF] = useState({ username: "", display_name: "", password: "", role: "hr" });
  const done = (m: string) => { toast(m); qc.invalidateQueries({ queryKey: ["accounts"] }); };
  const err = (e: unknown) => toast((e as Error).message, "error");
  const add = useMutation({ mutationFn: () => api.post("/api/accounts", f), onSuccess: () => { setAdding(false); setF({ username: "", display_name: "", password: "", role: "hr" }); done("Account created"); }, onError: err });
  const patch = useMutation({ mutationFn: (x: { u: string; body: Record<string, unknown> }) => api.patch(`/api/accounts/${x.u}`, x.body), onSuccess: () => done("Account updated"), onError: err });
  const del = useMutation({ mutationFn: (u: string) => api.del(`/api/accounts/${u}`), onSuccess: () => done("Account deleted"), onError: err });
  return (
    <section className="card">
      <div className="card-head"><h2>Accounts</h2><button className="btn primary sm" onClick={() => setAdding(true)}>+ Add account</button></div>
      <p className="muted"><b>Admin</b>: everything. <b>HR</b>: employees, departments, manual punches, exports. <b>Viewer</b>: look and export only.</p>
      <table className="tbl"><thead><tr><th>User</th><th>Role</th><th>Last sign-in</th><th /></tr></thead>
        <tbody>{accs.data?.rows.map((a) => (
          <tr key={a.username}>
            <td><b>{a.display_name || a.username}</b> <span className="muted mono">{a.username}</span>{a.locked_until && a.locked_until > new Date().toISOString().replace("T", " ") && <> <Pill tone="down">locked</Pill></>}</td>
            <td><select value={a.role} disabled={a.username === me.username} onChange={(e) => patch.mutate({ u: a.username, body: { role: e.target.value } })}>
              <option value="admin">Admin</option><option value="hr">HR</option><option value="viewer">Viewer</option></select></td>
            <td className="muted">{a.last_login ? ago(a.last_login) : "never"}</td>
            <td className="r nowrap">
              <button className="link" onClick={() => { const p = prompt(`New password for ${a.username} (8+ characters)`); if (p) patch.mutate({ u: a.username, body: { password: p } }); }}>Reset password</button>
              {a.locked_until && <button className="link" onClick={() => patch.mutate({ u: a.username, body: { unlock: true } })}>Unlock</button>}
              {a.username !== me.username && <button className="link danger" onClick={() => confirm(`Delete ${a.username}?`) && del.mutate(a.username)}>Delete</button>}
            </td>
          </tr>))}</tbody></table>
      {adding && <Modal title="New account" onClose={() => setAdding(false)}
        footer={<><button className="btn ghost" onClick={() => setAdding(false)}>Cancel</button><button className="btn primary" onClick={() => add.mutate()}>Create</button></>}>
        <div className="form two">
          <label>Username<input value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} /></label>
          <label>Display name<input value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} /></label>
          <label>Password<input type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></label>
          <label>Role<select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}><option value="hr">HR</option><option value="viewer">Viewer</option><option value="admin">Admin</option></select></label>
        </div>
      </Modal>}
    </section>
  );
}

const ACTION_LABEL: Record<string, string> = {
  sign_in: "Signed in", password_changed: "Changed own password", export: "Exported Excel", punch_added: "Added manual punch",
  punch_deleted: "Deleted manual punch", employee_added: "Added employee", employee_changed: "Edited employee",
  employees_bulk_changed: "Bulk edit", department_added: "Added department", department_renamed: "Renamed department",
  department_deleted: "Deleted department", device_added: "Added device", device_changed: "Edited device",
  settings_changed: "Changed settings", account_added: "Created account", account_changed: "Edited account",
  account_deleted: "Deleted account", legacy_imported: "Imported old program data", devices_seeded: "Seeded devices", account_saved: "Saved account (console)",
};
function Audit() {
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const a = useQuery({ queryKey: ["audit", page, q], queryFn: () => api.get<{ rows: { id: number; ts: string; username: string; action: string; target: string | null; detail: string | null }[]; total: number }>(`/api/audit?${qs({ page, q })}`) });
  return (
    <section className="card flush">
      <div className="card-head pad"><h2>Audit log</h2><input placeholder="Search user, action, target…" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} /></div>
      {a.data?.rows.length === 0 ? <Empty>Nothing yet.</Empty> :
        <table className="tbl"><thead><tr><th>When</th><th>User</th><th>Action</th><th>Target</th><th>Details</th></tr></thead>
          <tbody>{a.data?.rows.map((r) => <tr key={r.id}><td className="mono nowrap">{r.ts}</td><td>{r.username}</td><td>{ACTION_LABEL[r.action] ?? r.action}</td><td>{r.target}</td><td className="muted detail">{r.detail}</td></tr>)}</tbody></table>}
      <div className="tbl-foot"><span /><Pager page={page} size={50} total={a.data?.total ?? 0} onPage={setPage} /></div>
    </section>
  );
}

function Password() {
  const toast = useToast();
  const [f, setF] = useState({ current: "", new: "", again: "" });
  const m = useMutation({
    mutationFn: () => { if (f.new !== f.again) throw new Error("The new passwords do not match."); return api.post("/api/me/password", f); },
    onSuccess: () => { toast("Password changed"); setF({ current: "", new: "", again: "" }); },
    onError: (e) => toast((e as Error).message, "error"),
  });
  return (
    <section className="card narrow-card"><div className="form">
      <label>Current password<input type="password" value={f.current} onChange={(e) => setF({ ...f, current: e.target.value })} /></label>
      <label>New password (8+ characters)<input type="password" value={f.new} onChange={(e) => setF({ ...f, new: e.target.value })} /></label>
      <label>New password again<input type="password" value={f.again} onChange={(e) => setF({ ...f, again: e.target.value })} /></label>
      <button className="btn primary" onClick={() => m.mutate()}>Change password</button>
    </div></section>
  );
}
