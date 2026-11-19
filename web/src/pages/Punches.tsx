import Icon from "../components/Icon";
import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api, Department, Device, Employee, Punch, qs } from "../api";
import { can, useMe } from "../App";
import { Empty, Modal, MultiSelect, Option, Pager, Pill, SortTh, useToast } from "../components/ui";
import { empLabel, fmtDate, PRESETS, STATE_LABEL, today, WEEKDAYS } from "../util";

type Filters = {
  from: string; to: string; badge: string[]; department: string[]; device: string[]; source: string[];
  time_from: string; time_to: string; weekday: string[]; employee_status: string; q: string; dt_from: string; dt_to: string;
};
const EMPTY: Filters = { from: today(), to: today(), badge: [], department: [], device: [], source: [], time_from: "", time_to: "", weekday: [], employee_status: "", q: "", dt_from: "", dt_to: "" };
const LIST_KEYS = ["badge", "department", "device", "source", "weekday"] as const;
const VIEWS_KEY = "att.savedViews";

function fromUrl(sp: URLSearchParams): Filters {
  const f: Filters = { ...EMPTY };
  for (const k of Object.keys(EMPTY) as (keyof Filters)[]) {
    if ((LIST_KEYS as readonly string[]).includes(k)) (f as any)[k] = sp.getAll(k);
    else if (sp.get(k)) (f as any)[k] = sp.get(k);
  }
  return f;
}

export default function Punches() {
  const me = useMe();
  const toast = useToast();
  const qc = useQueryClient();
  const [sp, setSp] = useSearchParams();
  const [f, setF] = useState<Filters>(() => fromUrl(sp));
  const [qInput, setQInput] = useState(f.q);
  const [sort, setSort] = useState("ts");
  const [dir, setDir] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(50);
  const [adding, setAdding] = useState(false);
  const [views, setViews] = useState<{ name: string; filters: Filters }[]>(() => { try { return JSON.parse(localStorage.getItem(VIEWS_KEY) || "[]"); } catch { return []; } });

  const deps = useQuery({ queryKey: ["departments"], queryFn: () => api.get<{ rows: Department[] }>("/api/departments") });
  const devs = useQuery({ queryKey: ["devices"], queryFn: () => api.get<{ rows: Device[] }>("/api/devices") });
  const emps = useQuery({ queryKey: ["employees"], queryFn: () => api.get<{ rows: Employee[] }>("/api/employees"), staleTime: 60_000 });

  // a link from the overview can carry a department name
  useEffect(() => {
    const dn = sp.get("department_name");
    if (dn && deps.data) {
      const d = deps.data.rows.find((x) => x.name === dn);
      setF((o) => ({ ...o, department: d ? [String(d.id)] : ["none"] }));
      sp.delete("department_name"); setSp(sp, { replace: true });
    }
  }, [deps.data]); // eslint-disable-line

  useEffect(() => { const t = setTimeout(() => setF((o) => (o.q === qInput ? o : { ...o, q: qInput })), 350); return () => clearTimeout(t); }, [qInput]);
  useEffect(() => { setPage(1); setSp(qs(f as any), { replace: true }); }, [f]); // eslint-disable-line

  const query = qs({ ...(f as any), sort, dir, page, size });
  const list = useQuery({
    queryKey: ["punches", query], queryFn: () => api.get<{ rows: Punch[]; total: number; people: number }>(`/api/punches?${query}`),
    placeholderData: keepPreviousData, refetchInterval: f.to >= today() ? 30_000 : false,
  });

  const empOpts: Option[] = useMemo(() => (emps.data?.rows ?? []).map((e) => ({ value: e.badge, label: empLabel(e), hint: `device ${e.badge}${e.department ? " · " + e.department : ""}` })), [emps.data]);
  const depOpts: Option[] = useMemo(() => [...(deps.data?.rows ?? []).map((d) => ({ value: String(d.id), label: d.name })), { value: "none", label: "No department" }], [deps.data]);
  const devOpts: Option[] = useMemo(() => [...(devs.data?.rows ?? []).map((d) => ({ value: String(d.id), label: d.name, hint: d.retired ? "retired" : d.ip ?? "" })), { value: "manual", label: "Manual punches" }], [devs.data]);

  const set = <K extends keyof Filters>(k: K, v: Filters[K]) => setF((o) => ({ ...o, [k]: v }));
  const onSort = (id: string) => { if (id === sort) setDir(dir === "asc" ? "desc" : "asc"); else { setSort(id); setDir(id === "ts" ? "desc" : "asc"); } };
  const exact = !!(f.dt_from || f.dt_to);
  const setExact = (on: boolean) => setF((o) => on
    ? { ...o, dt_from: `${o.from}T06:00`, dt_to: `${o.to}T08:00`, time_from: "", time_to: "", weekday: [] }
    : { ...o, from: (o.dt_from || o.from).slice(0, 10), to: (o.dt_to || o.to).slice(0, 10), dt_from: "", dt_to: "" });
  const activeCount = LIST_KEYS.reduce((n, k) => n + (f[k].length ? 1 : 0), 0) + (f.time_from ? 1 : 0) + (f.time_to ? 1 : 0) + (f.employee_status ? 1 : 0) + (f.q ? 1 : 0);
  const preset = PRESETS.find((p) => { const [a, b] = p.range(); return a === f.from && b === f.to; })?.label;

  const del = useMutation({
    mutationFn: (id: number) => api.del(`/api/punches/${id}`),
    onSuccess: () => { toast("Manual punch deleted"); qc.invalidateQueries({ queryKey: ["punches"] }); },
    onError: (e) => toast((e as Error).message, "error"),
  });

  const saveView = () => {
    const name = prompt("Name this view (filters are saved in this browser):");
    if (!name) return;
    const next = [...views.filter((v) => v.name !== name), { name, filters: f }];
    setViews(next); localStorage.setItem(VIEWS_KEY, JSON.stringify(next)); toast(`View "${name}" saved`);
  };
  const dropView = (name: string) => { const next = views.filter((v) => v.name !== name); setViews(next); localStorage.setItem(VIEWS_KEY, JSON.stringify(next)); };

  return (
    <div className="page">
      <header className="page-head">
        <div><h1 className="with-ic"><span className="title-ic"><Icon name="finger" size={22} /></span>Punches</h1><p className="muted">{list.data ? `${list.data.total.toLocaleString()} punches by ${list.data.people.toLocaleString()} people` : "Loading…"}{exact ? ` · ${f.dt_from.replace("T", " ")} → ${f.dt_to.replace("T", " ")}` : preset ? ` · ${preset}` : ""}</p></div>
        <div className="actions">
          {can(me, "admin", "hr") && <button className="btn ghost" onClick={() => setAdding(true)}>+ Manual punch</button>}
          <a className="btn ghost" href={`/api/punches/export-old.xls?${qs(f as any)}`} title="Same file as the old program's Export: HR formulas work on it">⤓ Old format (.xls)</a>
          <a className="btn primary" href={`/api/punches/export.xlsx?${qs(f as any)}`}>⤓ Excel report</a>
        </div>
      </header>

      <section className="filters card">
        <div className="frow">
          <div className="field"><span className="ms-label">Range</span>
            <div className="seg"><button className={!exact ? "on" : ""} onClick={() => setExact(false)}>Whole days</button><button className={exact ? "on" : ""} onClick={() => setExact(true)} title="Like the old program: from a date and time to a date and time">Exact date &amp; time</button></div></div>
          {exact ? <>
            <div className="field"><span className="ms-label">From</span><input type="datetime-local" value={f.dt_from} onChange={(e) => set("dt_from", e.target.value)} /></div>
            <div className="field"><span className="ms-label">To</span><input type="datetime-local" value={f.dt_to} min={f.dt_from} onChange={(e) => set("dt_to", e.target.value)} /></div>
          </> : <>
            <div className="field"><span className="ms-label">From</span><input type="date" value={f.from} max={f.to} onChange={(e) => set("from", e.target.value)} /></div>
            <div className="field"><span className="ms-label">To</span><input type="date" value={f.to} min={f.from} onChange={(e) => set("to", e.target.value)} /></div>
            <div className="chips">{PRESETS.map((p) => <button key={p.label} className={`chip ${preset === p.label ? "on" : ""}`} onClick={() => { const [a, b] = p.range(); setF((o) => ({ ...o, from: a, to: b })); }}>{p.label}</button>)}</div>
          </>}
        </div>
        <div className="frow">
          <MultiSelect label="Employees" options={empOpts} value={f.badge} onChange={(v) => set("badge", v)} width={220} />
          <MultiSelect label="Departments" options={depOpts} value={f.department} onChange={(v) => set("department", v)} />
          <MultiSelect label="Devices" options={devOpts} value={f.device} onChange={(v) => set("device", v)} />
          <MultiSelect label="Source" options={[{ value: "device", label: "Device (this system)" }, { value: "legacy", label: "Imported (old program)" }, { value: "manual", label: "Manual" }]} value={f.source} onChange={(v) => set("source", v)} />
          <div className="field"><span className="ms-label">Employee status</span>
            <select value={f.employee_status} onChange={(e) => set("employee_status", e.target.value)}><option value="">All</option><option value="active">Active</option><option value="inactive">Inactive</option></select></div>
        </div>
        <div className="frow">
          {!exact && <>
          <div className="field"><span className="ms-label">Time from</span><input type="time" value={f.time_from} onChange={(e) => set("time_from", e.target.value)} /></div>
          <div className="field"><span className="ms-label">Time to</span><input type="time" value={f.time_to} onChange={(e) => set("time_to", e.target.value)} /></div>
          <div className="field"><span className="ms-label">Weekdays</span>
            <div className="chips tight">{WEEKDAYS.map((d, i) => { const on = f.weekday.includes(String(i)); return <button key={d} className={`chip ${on ? "on" : ""}`} onClick={() => set("weekday", on ? f.weekday.filter((x) => x !== String(i)) : [...f.weekday, String(i)])}>{d}</button>; })}</div></div>
          </>}
          <div className="field grow"><span className="ms-label">Search</span><input placeholder="Name, employee no. or note" value={qInput} onChange={(e) => setQInput(e.target.value)} /></div>
        </div>
        <div className="frow foot">
          <span className="muted">{activeCount ? `${activeCount} filter${activeCount > 1 ? "s" : ""} on` : "No filters"}</span>
          {activeCount > 0 && <button className="link" onClick={() => { setQInput(""); setF((o) => ({ ...EMPTY, from: o.from, to: o.to })); }}>Clear filters</button>}
          <span className="grow" />
          {views.map((v) => <span key={v.name} className="view-chip"><button onClick={() => { setQInput(v.filters.q); setF({ ...EMPTY, ...v.filters }); }}>{v.name}</button><i onClick={() => dropView(v.name)}>✕</i></span>)}
          <button className="btn sm ghost" onClick={saveView}>☆ Save view</button>
        </div>
      </section>

      <section className="card flush">
        <div className="tbl-wrap">
          <table className={`tbl ${list.isFetching ? "fetching" : ""}`}>
            <thead><tr>
              <SortTh id="ts" sort={sort} dir={dir} onSort={onSort}>Date</SortTh>
              <th>Time</th>
              <SortTh id="emp_no" sort={sort} dir={dir} onSort={onSort}>Emp No.</SortTh>
              <SortTh id="name" sort={sort} dir={dir} onSort={onSort}>Name</SortTh>
              <SortTh id="badge" sort={sort} dir={dir} onSort={onSort}>Device ID</SortTh>
              <SortTh id="department" sort={sort} dir={dir} onSort={onSort}>Department</SortTh>
              <SortTh id="device" sort={sort} dir={dir} onSort={onSort}>Device</SortTh>
              <th>State</th>
              <SortTh id="source" sort={sort} dir={dir} onSort={onSort}>Source</SortTh>
              <th>Note</th><th />
            </tr></thead>
            <tbody>
              {list.data?.rows.map((p) => (
                <tr key={p.id}>
                  <td className="nowrap">{fmtDate(p.ts)}</td>
                  <td className="mono strong">{p.ts.slice(11, 19)}</td>
                  <td className="mono"><button className="link strong" title="Show only this employee" onClick={() => set("badge", [p.badge])}>{p.emp_no || "—"}</button></td>
                  <td>{p.name || <span className="muted">no name</span>}</td>
                  <td className="mono muted">{p.badge}</td>
                  <td>{p.department || <span className="muted">—</span>}</td>
                  <td>{p.device ?? <span className="muted">—</span>}</td>
                  <td className="muted">{p.state !== null ? STATE_LABEL[p.state] ?? p.state : ""}</td>
                  <td><Pill tone={p.source === "manual" ? "quiet" : p.source === "legacy" ? "muted" : "info"}>{p.source === "legacy" ? "imported" : p.source}</Pill></td>
                  <td className="muted note" title={p.note ?? ""}>{p.note}{p.created_by && p.source === "manual" ? ` · ${p.created_by}` : ""}</td>
                  <td className="r">{p.source === "manual" && p.created_by !== "old program" && can(me, "admin", "hr") &&
                    <button className="link danger" onClick={() => confirm(`Delete the manual punch of ${p.name || p.badge} at ${p.ts}?`) && del.mutate(p.id)}>Delete</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {list.data && list.data.rows.length === 0 && <Empty>No punches match these filters.</Empty>}
        </div>
        <div className="tbl-foot">
          <select value={size} onChange={(e) => { setSize(+e.target.value); setPage(1); }}>{[25, 50, 100, 250].map((s) => <option key={s} value={s}>{s} per page</option>)}</select>
          <Pager page={page} size={size} total={list.data?.total ?? 0} onPage={setPage} />
        </div>
      </section>

      {adding && <AddPunch options={empOpts} onClose={() => setAdding(false)} onDone={() => { setAdding(false); qc.invalidateQueries({ queryKey: ["punches"] }); }} />}
    </div>
  );
}

function AddPunch({ options, onClose, onDone }: { options: Option[]; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [badge, setBadge] = useState<string[]>([]);
  const [ts, setTs] = useState(`${today()}T07:00`);
  const [note, setNote] = useState("Forgot to punch");
  const m = useMutation({
    mutationFn: () => api.post("/api/punches", { badge: badge[0], ts, note }),
    onSuccess: () => { toast("Manual punch added"); onDone(); },
    onError: (e) => toast((e as Error).message, "error"),
  });
  return (
    <Modal title="Add a manual punch" onClose={onClose}
      footer={<><button className="btn ghost" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!badge.length || m.isPending} onClick={() => m.mutate()}>Add punch</button></>}>
      <p className="muted">For an employee who forgot to punch. It is marked as manual, with your name and the reason, in every report.</p>
      <div className="form">
        <MultiSelect label="Employee" options={options} value={badge} onChange={(v) => setBadge(v.slice(-1))} placeholder="Choose…" />
        <label>Date and time<input type="datetime-local" value={ts} onChange={(e) => setTs(e.target.value)} /></label>
        <label>Reason<input value={note} onChange={(e) => setNote(e.target.value)} /></label>
      </div>
    </Modal>
  );
}
