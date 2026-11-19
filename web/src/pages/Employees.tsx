import Icon from "../components/Icon";
import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api, Department, Employee, Punch, qs } from "../api";
import { can, useMe } from "../App";
import { Empty, Modal, MultiSelect, Pill, SortTh, Spinner, useToast } from "../components/ui";
import { ago, fmtDate, iso, normNo } from "../util";
import { Biometrics } from "./Enroll";

type SortKey = "emp_no" | "badge" | "name" | "department" | "last_punch" | "days_30";

export default function Employees() {
  const me = useMe();
  const toast = useToast();
  const qc = useQueryClient();
  const emps = useQuery({ queryKey: ["employees"], queryFn: () => api.get<{ rows: Employee[] }>("/api/employees") });
  const deps = useQuery({ queryKey: ["departments"], queryFn: () => api.get<{ rows: Department[] }>("/api/departments") });
  const [sp] = useSearchParams();
  const [q, setQ] = useState(sp.get("q") ?? "");
  const [dep, setDep] = useState<string[]>([]);
  const [status, setStatus] = useState("active");
  const [sort, setSort] = useState<SortKey>("emp_no");
  const [dir, setDir] = useState<"asc" | "desc">("asc");
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [open, setOpen] = useState<Employee | "new" | null>(null);
  const editable = can(me, "admin", "hr");

  const rows = useMemo(() => {
    const s = q.trim().toLowerCase();
    const dev = s.startsWith("#") ? s.slice(1) : null;   // "#12" searches the device ID
    const cutoff = (() => { const d = new Date(); d.setDate(d.getDate() - 30); return iso(d); })();
    let r = (emps.data?.rows ?? []).filter((e) =>
      (!s || (dev !== null ? e.badge === dev : (normNo(e.emp_no) === normNo(s) && /^\d+$/.test(s)) || e.name.toLowerCase().includes(s) ||
        e.title.toLowerCase().includes(s) || (s.length > 3 && e.card.includes(s)))) &&
      (!dep.length || dep.includes(e.department_id === null ? "none" : String(e.department_id))) &&
      (status === "" || (status === "active" && e.active) || (status === "inactive" && !e.active) ||
        (status === "silent" && e.active && (!e.last_punch || e.last_punch < cutoff)) || (status === "no_number" && !e.emp_no)));
    const k = sort;
    r = [...r].sort((a, b) => {
      const val = (e: Employee) => k === "badge" ? +e.badge : k === "emp_no" ? (e.emp_no ? +normNo(e.emp_no) : 1e9) : k === "days_30" ? e.days_30 : (e[k] ?? "");
      const va = val(a), vb = val(b);
      return (va < vb ? -1 : va > vb ? 1 : 0) * (dir === "asc" ? 1 : -1);
    });
    return r;
  }, [emps.data, q, dep, status, sort, dir]);

  const bulk = useMutation({
    mutationFn: (set: Record<string, unknown>) => api.post<{ changed: number }>("/api/employees/bulk", { ids: [...sel], set }),
    onSuccess: (r) => { toast(`${r.changed} employees updated`); setSel(new Set()); qc.invalidateQueries({ queryKey: ["employees"] }); qc.invalidateQueries({ queryKey: ["departments"] }); },
    onError: (e) => toast((e as Error).message, "error"),
  });

  const onSort = (id: string) => { if (id === sort) setDir(dir === "asc" ? "desc" : "asc"); else { setSort(id as SortKey); setDir(id === "last_punch" || id === "days_30" ? "desc" : "asc"); } };
  const allOn = rows.length > 0 && rows.every((r) => sel.has(r.id));
  const depOpts = [...(deps.data?.rows ?? []).map((d) => ({ value: String(d.id), label: d.name, hint: `${d.employees}` })), { value: "none", label: "No department" }];

  if (emps.isLoading) return <div className="page"><Spinner /></div>;
  return (
    <div className="page">
      <header className="page-head">
        <div><h1 className="with-ic"><span className="title-ic"><Icon name="users" size={22} /></span>Employees</h1><p className="muted">{rows.length} shown · {emps.data?.rows.filter((e) => e.active).length} active in total</p></div>
        {editable && <div className="actions"><button className="btn primary" onClick={() => setOpen("new")}>+ Add employee</button></div>}
      </header>

      <section className="filters card">
        <div className="frow">
          <div className="field grow"><span className="ms-label">Search</span><input placeholder="Name, employee no., title, card · #12 for device ID" value={q} onChange={(e) => setQ(e.target.value)} autoFocus /></div>
          <MultiSelect label="Departments" options={depOpts} value={dep} onChange={setDep} />
          <div className="field"><span className="ms-label">Status</span>
            <div className="seg">{[["active", "Active"], ["inactive", "Inactive"], ["silent", "No punch in 30 days"], ["no_number", "Missing Emp No."], ["", "All"]].map(([v, l]) =>
              <button key={v} className={status === v ? "on" : ""} onClick={() => setStatus(v)}>{l}</button>)}</div></div>
        </div>
      </section>

      {editable && sel.size > 0 && (
        <div className="bulkbar">
          <b>{sel.size} selected</b>
          <select defaultValue="" onChange={(e) => { if (e.target.value) bulk.mutate({ department_id: e.target.value }); e.target.value = ""; }}>
            <option value="" disabled>Move to department…</option>
            {deps.data?.rows.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            <option value="none">No department</option>
          </select>
          <button className="btn sm ghost" onClick={() => bulk.mutate({ active: false })}>Mark inactive</button>
          <button className="btn sm ghost" onClick={() => bulk.mutate({ active: true })}>Mark active</button>
          <button className="link" onClick={() => setSel(new Set())}>Clear selection</button>
        </div>
      )}

      <section className="card flush">
        <div className="tbl-wrap">
          <table className="tbl hover">
            <thead><tr>
              {editable && <th className="cb"><input type="checkbox" checked={allOn} onChange={() => setSel(allOn ? new Set() : new Set(rows.map((r) => r.id)))} /></th>}
              <SortTh id="emp_no" sort={sort} dir={dir} onSort={onSort}>Emp No.</SortTh>
              <SortTh id="name" sort={sort} dir={dir} onSort={onSort}>Name</SortTh>
              <SortTh id="badge" sort={sort} dir={dir} onSort={onSort}>Device ID</SortTh>
              <SortTh id="department" sort={sort} dir={dir} onSort={onSort}>Department</SortTh>
              <th>Title</th>
              <SortTh id="last_punch" sort={sort} dir={dir} onSort={onSort}>Last punch</SortTh>
              <SortTh id="days_30" sort={sort} dir={dir} onSort={onSort} className="r">Days (30d)</SortTh>
              <th>Status</th>
            </tr></thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.id} onClick={() => setOpen(e)} className={sel.has(e.id) ? "sel" : ""}>
                  {editable && <td className="cb" onClick={(x) => x.stopPropagation()}><input type="checkbox" checked={sel.has(e.id)} onChange={() => { const n = new Set(sel); n.has(e.id) ? n.delete(e.id) : n.add(e.id); setSel(n); }} /></td>}
                  <td className="mono strong">{e.emp_no || <span className="t-down" title="No employee number yet">missing</span>}</td>
                  <td><b>{e.name || <span className="muted">no name</span>}</b>{e.device_name && e.device_name !== e.name && <span className="muted small"> · on device: {e.device_name}</span>}</td>
                  <td className="mono muted">{e.badge}</td>
                  <td>{e.department ?? <span className="muted">—</span>}</td>
                  <td className="muted">{e.title}</td>
                  <td className="nowrap">{e.last_punch ? <span title={e.last_punch}>{ago(e.last_punch)}</span> : <span className="muted">never</span>}</td>
                  <td className="r"><span className="mini-meter"><i style={{ width: `${Math.min(100, (e.days_30 / 26) * 100)}%` }} /></span>{e.days_30}</td>
                  <td>{e.active ? <Pill tone="up">Active</Pill> : <Pill tone="muted">Inactive</Pill>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && <Empty>No employees match.</Empty>}
        </div>
      </section>

      {open && <EmployeeDrawer emp={open === "new" ? null : open} deps={deps.data?.rows ?? []} editable={editable}
        onClose={() => setOpen(null)} onSaved={() => { qc.invalidateQueries({ queryKey: ["employees"] }); qc.invalidateQueries({ queryKey: ["departments"] }); }} />}
    </div>
  );
}

function EmployeeDrawer({ emp, deps, editable, onClose, onSaved }: {
  emp: Employee | null; deps: Department[]; editable: boolean; onClose: () => void; onSaved: () => void;
}) {
  const toast = useToast();
  const admin = can(useMe(), "admin");
  const [form, setForm] = useState({
    badge: emp?.badge ?? "", emp_no: emp?.emp_no ?? "", phone: emp?.phone ?? "", name: emp?.name ?? "", department_id: emp?.department_id ? String(emp.department_id) : "",
    title: emp?.title ?? "", card: emp?.card ?? "", active: emp ? !!emp.active : true, note: emp?.note ?? "",
  });
  type Next = { badge_last: string | null; badge_last_name: string | null; badge_next: string; emp_no_last: string | null; emp_no_last_name: string | null; emp_no_next: string };
  const next = useQuery({ enabled: !emp && editable, queryKey: ["emp-next"], queryFn: () => api.get<Next>("/api/employees/next") });
  useEffect(() => {
    if (!next.data) return;
    setForm((f) => ({ ...f, badge: f.badge || next.data.badge_next, emp_no: f.emp_no || next.data.emp_no_next }));
  }, [next.data]);
  const from = (() => { const d = new Date(); d.setDate(d.getDate() - 30); return iso(d); })();
  const recent = useQuery({
    enabled: !!emp, queryKey: ["emp-punches", emp?.badge],
    queryFn: () => api.get<{ rows: Punch[]; total: number }>(`/api/punches?${qs({ from, to: iso(new Date()), badge: emp!.badge, size: 200 })}`),
  });
  const save = useMutation({
    mutationFn: () => emp ? api.patch(`/api/employees/${emp.id}`, form) : api.post("/api/employees", form),
    onSuccess: () => { toast(emp ? "Saved" : "Employee added"); onSaved(); onClose(); },
    onError: (e) => toast((e as Error).message, "error"),
  });
  const byDay = useMemo(() => {
    const m = new Map<string, string[]>();
    recent.data?.rows.forEach((p) => { const d = p.ts.slice(0, 10); m.set(d, [...(m.get(d) ?? []), p.ts.slice(11, 16)]); });
    return [...m.entries()].map(([d, t]) => [d, t.sort()] as const).sort((a, b) => (a[0] < b[0] ? 1 : -1));
  }, [recent.data]);
  const set = (k: string, v: unknown) => setForm((f) => ({ ...f, [k]: v }));
  return (
    <Modal drawer title={emp ? <>{emp.name || "No name"} <span className="muted mono">{emp.emp_no || "no Emp No."} · device {emp.badge}</span></> : "New employee"} onClose={onClose}
      footer={editable ? <><button className="btn ghost" onClick={onClose}>Cancel</button><button className="btn primary" disabled={save.isPending} onClick={() => save.mutate()}>{emp ? "Save changes" : "Add employee"}</button></> : undefined}>
      <div className="form two">
        <label>Employee No. (HR)<input value={form.emp_no} disabled={!editable} onChange={(e) => set("emp_no", e.target.value)} inputMode="numeric" className="mono" />
          {!emp && next.data?.emp_no_last && <span className="hint">Last used: <b className="mono">{next.data.emp_no_last}</b> {next.data.emp_no_last_name}</span>}</label>
        <label>Device ID (user number on the devices)<input value={form.badge} disabled={!!emp} onChange={(e) => set("badge", e.target.value)} inputMode="numeric" className="mono" />
          {!emp && next.data?.badge_last && <span className="hint">Last used: <b className="mono">{next.data.badge_last}</b> {next.data.badge_last_name ?? "(on a device only)"}</span>}</label>
        <label className="span2">Name (as shown on the devices)<span className={`name-count ${form.name.length >= 24 ? "full" : ""}`}>{form.name.length}/24</span>
          <input value={form.name} maxLength={24} disabled={!editable} onChange={(e) => set("name", e.target.value)} /></label>
        <label>Department<select value={form.department_id} disabled={!editable} onChange={(e) => set("department_id", e.target.value)}>
          <option value="">No department</option>{deps.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
        <label>Title<input value={form.title} disabled={!editable} onChange={(e) => set("title", e.target.value)} /></label>
        <label>Card number<input value={form.card} disabled={!editable} onChange={(e) => set("card", e.target.value)} /></label>
        <label>Phone<input value={form.phone} disabled={!editable} onChange={(e) => set("phone", e.target.value)} /></label>
        <label className="check-row"><input type="checkbox" checked={form.active} disabled={!editable} onChange={(e) => set("active", e.target.checked)} /> Active employee</label>
        <label className="span2">Note<textarea rows={2} value={form.note} disabled={!editable} onChange={(e) => set("note", e.target.value)} /></label>
      </div>
      {emp && <Biometrics badge={emp.badge} name={emp.name} admin={admin} />}
      {emp && (
        <div className="emp-recent">
          <div className="card-head"><h4>Last 30 days</h4><Link to={`/punches?${qs({ badge: emp.badge, from, to: iso(new Date()) })}`} onClick={onClose}>Open in Punches →</Link></div>
          {emp.device_name && <p className="muted small">Name stored on the devices: {emp.device_name}</p>}
          {recent.isLoading ? <Spinner /> : byDay.length === 0 ? <Empty>No punches in the last 30 days.</Empty> :
            <div className="day-list">{byDay.map(([d, t]) => (
              <div key={d} className="day-row"><span>{fmtDate(d + " 00:00:00")}</span>
                <span className="times">{t.map((x, i) => <i key={i}>{x}</i>)}</span>
                {t.length === 1 && <Pill tone="down">single</Pill>}</div>
            ))}</div>}
        </div>
      )}
    </Modal>
  );
}
