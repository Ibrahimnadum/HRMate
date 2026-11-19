import { Fragment, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Device, Job } from "../api";
import { can, useMe } from "../App";
import Icon from "../components/Icon";
import { Empty, Modal, Pill, Spinner, useToast } from "../components/ui";
import { ago, EVENT_LABEL, num } from "../util";

/* ---------- types ---------- */
interface OptEdit { type: "bool" | "ip" | "int" | "choice"; min?: number; max?: number; choices?: Record<string, string> }
interface OptSpec { key: string; tab: "info" | "advanced" | "power" | "comm"; label: string; edit: OptEdit | null }
interface Info {
  options: Record<string, string>; sizes: Record<string, number>; raw_sizes: number[]; firmware: string | null;
  admins: number; passwords: number; device_time: string | null;
}
interface Detail {
  device: Device & { info_at: string | null; machine_number: number | null; punches_stored: number };
  info: Info | null; events: { ts: string; kind: string; detail: string | null }[];
  catalog: OptSpec[]; actions: Record<string, string>; enroll_device_id: number | null;
}
type Queued = { id: number; waiting_for: string | null };

/* ---------- job progress, shown where the action was started ---------- */
export function JobWatch({ id, onDone }: { id: number; onDone?: (j: Job) => void }) {
  const q = useQuery({
    queryKey: ["jobs"], queryFn: () => api.get<{ rows: Job[] }>("/api/jobs"),
    refetchInterval: (query) => {
      const j = query.state.data?.rows.find((r) => r.id === id);
      return !j || j.status === "running" || j.status === "queued" ? 1500 : false;
    },
  });
  const job = q.data?.rows.find((r) => r.id === id);
  const finished = job && (job.status === "done" || job.status === "failed" || job.status === "cancelled");
  useEffect(() => { if (finished && job && onDone) onDone(job); }, [finished]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!job) return <div className="job-watch"><Spinner /></div>;
  const tone = { done: "up", failed: "down", running: "info", queued: "wait", cancelled: "muted" }[job.status] as "up";
  const lines = job.log.trim().split("\n").slice(-8);
  return (
    <div className={`job-watch ${job.status}`}>
      <div className="jw-head"><b>{job.title}</b><Pill tone={tone}>{job.status === "queued" ? "Waiting" : job.status}</Pill></div>
      {job.status === "running" && <div className="bar"><span style={{ width: `${Math.max(5, job.progress)}%` }} /></div>}
      <pre className="jw-log">{lines.join("\n") || "Waiting for the device ..."}</pre>
    </div>
  );
}

/* ---------- page ---------- */
const TABS = [["info", "Device info"], ["power", "Power"], ["advanced", "Advanced function"], ["comm", "Comm set"], ["history", "History"]] as const;

export default function DeviceManage() {
  const { id } = useParams();
  const me = useMe();
  const admin = can(me, "admin");
  const toast = useToast();
  const qc = useQueryClient();
  const [tab, setTab] = useState<(typeof TABS)[number][0]>("info");
  const [watch, setWatch] = useState<number | null>(null);
  const q = useQuery({ queryKey: ["device", id], queryFn: () => api.get<Detail>(`/api/devices/${id}`) });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["device", id] }); qc.invalidateQueries({ queryKey: ["devices"] }); };
  const queued = (r: Queued) => {
    setWatch(r.id);
    if (r.waiting_for) toast(`Queued. It starts after the board window (${r.waiting_for}).`);
  };
  const read = useMutation({
    mutationFn: () => api.post<Queued>(`/api/devices/${id}/read`),
    onSuccess: queued, onError: (e) => toast((e as Error).message, "error"),
  });

  if (q.isLoading || !q.data) return <Spinner />;
  const { device: d, info } = q.data;
  const tone = !d.active ? "muted" : d.online === 0 ? "down" : d.online === 1 ? "up" : "wait";
  const sel = (t: string) => q.data.catalog.filter((o) => o.tab === t);

  return (
    <div>
      <div className="dm-head card">
        <Link to="/devices" className="btn ghost sm"><Icon name="left" size={14} /> Devices</Link>
        <div className="grow">
          <h2>{d.name} <Pill tone={tone}>{!d.active ? "Not polled" : d.online === 0 ? "Offline" : d.online === 1 ? "Online" : "Checking"}</Pill></h2>
          <span className="muted mono">{d.ip}:{d.port}{d.machine_number != null ? ` · machine ${d.machine_number}` : ""}{d.model ? ` · ${d.model}` : ""}</span>
        </div>
        <span className="muted small">{d.info_at ? `Read from the device ${ago(d.info_at)}` : "Not read from the device yet"}</span>
        {admin && <button className="btn primary" disabled={read.isPending} onClick={() => read.mutate()}><Icon name="refresh" size={15} /> Read device</button>}
      </div>

      {watch && <JobWatch key={watch} id={watch} onDone={(j) => { refresh(); if (j.status === "failed") toast("The job failed. See the log.", "error"); }} />}

      <nav className="tabs">
        {TABS.map(([k, label]) => <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{label}</button>)}
      </nav>

      {!info && tab !== "history" && <div className="banner">Nothing read from this device yet.{admin ? " Press Read device; it takes a few seconds." : ""}</div>}

      {tab === "info" && info && <InfoTab d={d} info={info} specs={sel("info")} />}
      {tab === "power" && info && <OptionsTab id={d.id} info={info} specs={sel("power")} admin={admin} onQueued={queued}
        intro="Power schedules and idle behaviour. Values that are not confirmed for this firmware yet are shown but locked." extra={
          admin ? <ActionButtons id={d.id} name={d.name} which={["restart", "poweroff"]} labels={q.data.actions} onQueued={queued} /> : null} />}
      {tab === "advanced" && <>
        {admin && <ActionButtons id={d.id} name={d.name} which={["clock", "voice", "clear_attlog", "clear_oplog", "clear_admin", "initialize"]} labels={q.data.actions} onQueued={queued} />}
        {info && <OptionsTab id={d.id} info={info} specs={sel("advanced")} admin={admin} onQueued={queued} intro="Display and sound." />}
      </>}
      {tab === "comm" && info && <CommTab d={d} info={info} specs={sel("comm")} admin={admin} onQueued={queued} />}
      {tab === "history" && <section className="card flush">
        {q.data.events.length === 0 ? <Empty>No events for this device.</Empty> :
          <table className="tbl"><tbody>{q.data.events.map((e, i) => (
            <tr key={i}><td className="mono nowrap">{e.ts}</td><td><Pill tone={e.kind === "up" || e.kind === "pull_ok_after_error" ? "up" : e.kind.startsWith("device_") ? "info" : "down"}>{EVENT_LABEL[e.kind] ?? e.kind.replace("device_", "").replace(/_/g, " ")}</Pill></td>
              <td className="muted">{e.detail}</td><td className="muted r nowrap">{ago(e.ts)}</td></tr>))}</tbody></table>}
      </section>}
    </div>
  );
}

/* ---------- Device info ---------- */
function InfoTab({ d, info, specs }: { d: Detail["device"]; info: Info; specs: OptSpec[] }) {
  const s = info.sizes;
  const o = info.options;
  const counts: [string, number | undefined][] = [
    ["Users", s.users], ["Fingerprints", s.fingers], ["Faces", s.faces], ["Attendance logs", s.records],
    ["Super logs", s.super_logs], ["Administrators", s.admins ?? info.admins], ["Passwords", s.passwords ?? info.passwords],
  ];
  const caps: [string, number | undefined, number | undefined][] = [
    ["Users", s.users, s.users_cap], ["Fingerprints", s.fingers, s.fingers_cap], ["Faces", s.faces, s.faces_cap], ["Logs", s.records, s.records_cap],
  ];
  const drift = info.device_time ? Math.round((new Date(info.device_time.replace(" ", "T")).getTime() - Date.now()) / 60000) : null;
  return (
    <>
      <div className="grid-2">
        <section className="card">
          <div className="card-head"><h2>Counts</h2></div>
          <dl className="kv">
            {counts.map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd className="mono">{v != null ? num(v) : "—"}</dd></Fragment>)}
            <dt>Stored here</dt><dd className="mono">{num(d.punches_stored)} punches</dd>
          </dl>
        </section>
        <section className="card">
          <div className="card-head"><h2>Capacity</h2></div>
          {caps.map(([k, used, cap]) => {
            const pct = used != null && cap ? Math.min(100, (used / cap) * 100) : 0;
            return (
              <div key={k} className="cap-row">
                <div className="cap-label"><span>{k}</span><span className="mono muted">{used != null ? num(used) : "—"} / {cap ? num(cap) : "—"}</span></div>
                <div className={`bar ${pct > 85 ? "hot" : ""}`}><span style={{ width: `${pct}%` }} /></div>
              </div>
            );
          })}
        </section>
      </div>
      <section className="card">
        <div className="card-head"><h2>Information</h2></div>
        <dl className="kv cols">
          {specs.filter((sp) => o[sp.key] != null).map((sp) => <Fragment key={sp.key}><dt>{sp.label}</dt><dd className="mono">{sp.key === "FaceFunOn" ? (o[sp.key] === "1" ? "On" : "Off") : o[sp.key]}</dd></Fragment>)}
          <dt>Firmware</dt><dd className="mono">{info.firmware ?? d.firmware ?? "—"}</dd>
          <dt>Device clock</dt><dd className="mono">{info.device_time ?? "—"}{drift != null && Math.abs(drift) >= 1 ? <span className="t-down"> ({Math.abs(drift)} min {drift > 0 ? "ahead" : "behind"} at read time)</span> : ""}</dd>
        </dl>
      </section>
      <RawValues info={info} />
    </>
  );
}

function RawValues({ info }: { info: Info }) {
  const [open, setOpen] = useState(false);
  return (
    <p className="muted small">
      <button className="link" onClick={() => setOpen(!open)}>{open ? "Hide" : "Show"} every value read from the device</button>
      {open && <pre className="raw">{Object.entries(info.options).map(([k, v]) => `${k} = ${v}`).join("\n")}{"\n\ncounters: " + info.raw_sizes.join(", ")}</pre>}
    </p>
  );
}

/* ---------- editable options (Power, Advanced) ---------- */
function OptionsTab({ id, info, specs, admin, onQueued, intro, extra }: {
  id: number; info: Info; specs: OptSpec[]; admin: boolean; onQueued: (r: Queued) => void; intro: string; extra?: React.ReactNode;
}) {
  const toast = useToast();
  const present = specs.filter((s) => info.options[s.key] != null);
  const [vals, setVals] = useState<Record<string, string>>({});
  const changed = Object.entries(vals).filter(([k, v]) => v !== info.options[k]);
  const save = useMutation({
    mutationFn: () => api.put<Queued>(`/api/devices/${id}/options`, { values: Object.fromEntries(changed) }),
    onSuccess: (r) => { setVals({}); onQueued(r); }, onError: (e) => toast((e as Error).message, "error"),
  });
  return (
    <>
      {extra}
      <section className="card">
        <div className="card-head"><h2>Settings</h2><span className="muted small">{intro}</span></div>
        {present.length === 0 ? <Empty>This device did not report any of these settings.</Empty> :
          <div className="opt-list">
            {present.map((s) => (
              <div key={s.key} className="opt-row">
                <div><b>{s.label}</b><span className="mono muted small"> {s.key}</span></div>
                <OptInput spec={s} value={vals[s.key] ?? info.options[s.key]} disabled={!admin || !s.edit} onChange={(v) => setVals((o) => ({ ...o, [s.key]: v }))} />
                {!s.edit && <span className="pill muted" title="Shown as the device reports it. Editing opens once we confirm what the values mean on this firmware.">locked</span>}
              </div>
            ))}
          </div>}
        {admin && present.some((s) => s.edit) && <div className="card-foot">
          <button className="btn ghost" disabled={!changed.length} onClick={() => setVals({})}>Undo</button>
          <button className="btn primary" disabled={!changed.length || save.isPending} onClick={() => save.mutate()}>Write {changed.length || ""} change{changed.length === 1 ? "" : "s"} to the device</button>
        </div>}
      </section>
    </>
  );
}

function OptInput({ spec, value, disabled, onChange }: { spec: OptSpec; value: string; disabled: boolean; onChange: (v: string) => void }) {
  const e = spec.edit;
  if (!e) return <span className="mono">{value}</span>;
  if (e.type === "bool") return (
    <div className="seg">{[["1", "On"], ["0", "Off"]].map(([v, l]) => (
      <button key={v} type="button" disabled={disabled} className={value === v ? "on" : ""} onClick={() => onChange(v)}>{l}</button>))}</div>);
  if (e.type === "choice") return (
    <select disabled={disabled} value={value} onChange={(ev) => onChange(ev.target.value)}>
      {!(value in (e.choices ?? {})) && <option value={value}>{value} (unknown)</option>}
      {Object.entries(e.choices ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
    </select>);
  return <input className="mono" disabled={disabled} value={value} type={e.type === "int" ? "number" : "text"} min={e.min} max={e.max} onChange={(ev) => onChange(ev.target.value)} />;
}

/* ---------- functions ---------- */
const ACTION_INFO: Record<string, { text: string; danger?: boolean; typed?: boolean; icon: string }> = {
  restart: { text: "Restarts the device. It is unavailable for about a minute.", icon: "refresh" },
  poweroff: { text: "Turns the device off. Someone must switch it on at the device.", danger: true, icon: "logout" },
  clock: { text: "Sets the device clock to the server time.", icon: "clock" },
  voice: { text: "Plays \"Thank you\" so you can find which device this is.", icon: "bell" },
  clear_attlog: { text: "Deletes the attendance logs on the device. Every log is saved here first; nothing is cleared if one is missing.", danger: true, typed: true, icon: "finger" },
  clear_oplog: { text: "Deletes the device's operation (super) log. Attendance is not touched.", icon: "chart" },
  clear_admin: { text: "Removes admin rights from everyone on the device. Its menu opens to anyone until an admin is set again.", danger: true, typed: true, icon: "users" },
  initialize: { text: "Wipes users, fingerprints, faces and logs. Everything is backed up here first so it can be copied back.", danger: true, typed: true, icon: "device" },
};

function ActionButtons({ id, name, which, labels, onQueued }: { id: number; name: string; which: string[]; labels: Record<string, string>; onQueued: (r: Queued) => void }) {
  const toast = useToast();
  const [ask, setAsk] = useState<string | null>(null);
  const [typed, setTyped] = useState("");
  const go = useMutation({
    mutationFn: (a: string) => a === "clock"
      ? api.post<Queued>("/api/jobs", { kind: "clock", device_ids: [id] })
      : api.post<Queued>(`/api/devices/${id}/action`, { action: a, confirm: typed }),
    onSuccess: (r) => { setAsk(null); setTyped(""); onQueued(r); }, onError: (e) => toast((e as Error).message, "error"),
  });
  const label = (a: string) => a === "clock" ? "Sync time" : labels[a];
  const info = ask ? ACTION_INFO[ask] : null;
  return (
    <section className="card">
      <div className="card-head"><h2>Functions</h2></div>
      <div className="fn-grid">
        {which.map((a) => (
          <button key={a} className={`fn ${ACTION_INFO[a].danger ? "danger" : ""}`} onClick={() => setAsk(a)}>
            <Icon name={ACTION_INFO[a].icon} size={18} /><span><b>{label(a)}</b><small>{ACTION_INFO[a].text}</small></span>
          </button>
        ))}
      </div>
      {ask && info && (
        <Modal title={`${label(ask)}: ${name}`} onClose={() => { setAsk(null); setTyped(""); }}
          footer={<><button className="btn ghost" onClick={() => setAsk(null)}>Cancel</button>
            <button className={`btn ${info.danger ? "danger" : "primary"}`} disabled={go.isPending || (info.typed && typed.trim() !== name)} onClick={() => go.mutate(ask)}>{label(ask)}</button></>}>
          <p>{info.text}</p>
          {info.typed && <label className="form">Type <b className="mono">{name}</b> to confirm<input value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus /></label>}
        </Modal>
      )}
    </section>
  );
}

/* ---------- Comm set ---------- */
function CommTab({ d, info, specs, admin, onQueued }: { d: Detail["device"]; info: Info; specs: OptSpec[]; admin: boolean; onQueued: (r: Queued) => void }) {
  const toast = useToast();
  const editable = specs.filter((s) => s.edit && (info.options[s.key] != null || s.key === "COMKey"));
  const readonly = specs.filter((s) => !s.edit && info.options[s.key] != null);
  const [vals, setVals] = useState<Record<string, string>>({});
  const [confirm, setConfirm] = useState<string | null>(null);
  const changed = useMemo(() => Object.entries(vals).filter(([k, v]) => v !== "" && v !== info.options[k]), [vals, info]);
  const save = useMutation({
    mutationFn: () => api.put<Queued>(`/api/devices/${d.id}/options`, { values: Object.fromEntries(changed), confirm }),
    onSuccess: (r) => { setVals({}); setConfirm(null); onQueued(r); }, onError: (e) => toast((e as Error).message, "error"),
  });
  return (
    <section className="card">
      <div className="card-head"><h2>Communication</h2><span className="muted small">After saving, the server switches to the new values and checks that the device answers.</span></div>
      <div className="opt-list">
        {editable.map((s) => (
          <div key={s.key} className="opt-row">
            <div><b>{s.label}</b>{s.key === "DeviceID" && <span className="muted small"> shown as Location ID on new punches</span>}</div>
            {s.key === "COMKey"
              ? <input type="password" className="mono" disabled={!admin} placeholder="unchanged" value={vals.COMKey ?? ""} onChange={(e) => setVals((o) => ({ ...o, COMKey: e.target.value }))} />
              : <input className="mono" disabled={!admin} value={vals[s.key] ?? info.options[s.key] ?? ""} onChange={(e) => setVals((o) => ({ ...o, [s.key]: e.target.value }))} />}
          </div>
        ))}
        {readonly.map((s) => <div key={s.key} className="opt-row"><div><b>{s.label}</b></div><span className="mono">{info.options[s.key]}</span><span className="pill muted">locked</span></div>)}
      </div>
      {admin && <div className="card-foot">
        <button className="btn ghost" disabled={!changed.length} onClick={() => setVals({})}>Undo</button>
        <button className="btn primary" disabled={!changed.length} onClick={() => setConfirm("")}>Save to device</button>
      </div>}
      {confirm !== null && (
        <Modal title={`Change communication settings: ${d.name}`} onClose={() => setConfirm(null)}
          footer={<><button className="btn ghost" onClick={() => setConfirm(null)}>Cancel</button>
            <button className="btn danger" disabled={save.isPending || confirm.trim() !== d.name} onClick={() => save.mutate()}>Save</button></>}>
          <ul>{changed.map(([k, v]) => <li key={k}>{specs.find((s) => s.key === k)?.label}: <b className="mono">{k === "COMKey" ? "****" : v}</b></li>)}</ul>
          {changed.some(([k]) => k !== "DeviceID" && k !== "COMKey") && <p>The device restarts to use the new network settings.</p>}
          <p className="muted small">A wrong IP or comm key can only be fixed at the device menu.</p>
          <label className="form">Type <b className="mono">{d.name}</b> to confirm<input value={confirm} onChange={(e) => setConfirm(e.target.value)} autoFocus /></label>
        </Modal>
      )}
    </section>
  );
}
