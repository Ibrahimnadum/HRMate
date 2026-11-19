import Icon from "../components/Icon";
import { useState } from "react";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import DeviceUsers from "./DeviceUsers";
import DeviceManage from "./DeviceManage";
import Jobs, { useQueueJob } from "./Jobs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, CollectorState, Device, EventRow, qs } from "../api";
import { can, useMe } from "../App";
import { Empty, Modal, Pager, Pill, Spinner, useToast } from "../components/ui";
import { ago, EVENT_LABEL, num } from "../util";
import { deviceTone } from "./Overview";

export default function Devices() {
  return (
    <div className="page">
      <header className="page-head"><div><h1 className="with-ic"><span className="title-ic"><Icon name="device" size={22} /></span>Devices</h1></div></header>
      <nav className="tabs">
        <NavLink to="/devices" end className={({ isActive }) => (isActive ? "on" : "")}>Status</NavLink>
        <NavLink to="/devices/users" className={({ isActive }) => (isActive ? "on" : "")}>Users on devices</NavLink>
        <NavLink to="/devices/jobs" className={({ isActive }) => (isActive ? "on" : "")}>Jobs</NavLink>
      </nav>
      <Routes>
        <Route index element={<Status />} />
        <Route path="users" element={<DeviceUsers />} />
        <Route path="jobs" element={<Jobs />} />
        <Route path=":id" element={<DeviceManage />} />
      </Routes>
    </div>
  );
}

function Status() {
  const me = useMe();
  const admin = can(me, "admin");
  const toast = useToast();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["devices"], queryFn: () => api.get<{ rows: Device[]; collector: CollectorState }>("/api/devices"), refetchInterval: 15_000 });
  const [edit, setEdit] = useState<Device | "new" | null>(null);
  const [evDevice, setEvDevice] = useState("");
  const [evKind, setEvKind] = useState("");
  const [evPage, setEvPage] = useState(1);
  const [showRetired, setShowRetired] = useState(false);
  const events = useQuery({
    queryKey: ["events", evDevice, evKind, evPage],
    queryFn: () => api.get<{ rows: EventRow[]; total: number }>(`/api/events?${qs({ device: evDevice, kind: evKind, page: evPage })}`),
    refetchInterval: 30_000,
  });
  const pull = useMutation({
    mutationFn: (ids?: number[]) => api.post("/api/devices/pull", { ids }),
    onSuccess: () => { toast("Pull started. Cards update within a minute."); setTimeout(() => qc.invalidateQueries({ queryKey: ["devices"] }), 15000); },
    onError: (e) => toast((e as Error).message, "error"),
  });

  const queue = useQueueJob();
  if (list.isLoading || !list.data) return <Spinner />;
  const quiet = list.data.collector.quiet_until;
  const current = list.data.rows.filter((d) => !d.retired);
  const retired = list.data.rows.filter((d) => d.retired);
  return (
    <div>
      <div className="sub-head">
        <p className="muted">Port 4370 is checked every minute and logs are pulled every 10 minutes, except during Activity Board windows.</p>
        {admin && <div className="actions">
          <button className="btn ghost" onClick={() => setEdit("new")}>+ Add device</button>
          <button className="btn ghost" onClick={() => queue({ kind: "clock" })}>◷ Set all clocks</button>
          <button className="btn primary" disabled={!!quiet || pull.isPending} onClick={() => pull.mutate(undefined)} title={quiet ? `Board window until ${quiet}` : ""}>⟳ Pull all now</button>
        </div>}
      </div>
      {quiet && <div className="banner quiet"><b>Activity Board window until {quiet}.</b> Status below is from before the window; no connections are made until it ends.</div>}

      <section className="dev-grid">
        {current.map((d) => {
          const tone = deviceTone(d, d.active ? quiet : null);
          return (
            <div key={d.id} className={`dev-card ${d.active ? tone : "off"}`}>
              <div className="dc-head">
                <span className="dot" />
                <div className="grow"><h3><Link to={`/devices/${d.id}`}>{d.name}</Link></h3><span className="mono muted">{d.ip}:{d.port}</span></div>
                {!d.active ? <Pill tone="muted">Not polled</Pill> : <Pill tone={tone}>{{ up: "Online", down: "Offline", wait: "Checking", quiet: "Board window" }[tone]}</Pill>}
              </div>
              <dl>
                <dt>{d.online === 0 ? "Offline since" : "Online since"}</dt><dd>{d.status_since ? ago(d.status_since) : "—"}</dd>
                <dt>Last pull</dt><dd>{ago(d.last_pull_at)}</dd>
                <dt>On the device</dt><dd>{d.records_on_device !== null ? `${num(d.records_on_device)} logs · ${num(d.users_on_device)} users` : "—"}</dd>
                <dt>Fingerprints / faces</dt><dd>{d.fingers_on_device != null ? `${num(d.fingers_on_device)}${d.fingers_cap ? " / " + num(d.fingers_cap) : ""}` : "—"} · {d.faces_on_device != null ? num(d.faces_on_device) : "—"}</dd>
                <dt>Stored here</dt><dd>{num(d.punches_stored)} punches</dd>
                <dt>Drops, 7 days</dt><dd className={d.drops_7d ? "t-down" : ""}>{d.drops_7d ?? 0}</dd>
                <dt>Clock</dt><dd>{d.device_time_offset === null ? "—" : Math.abs(d.device_time_offset) < 60 ? "in sync" : <span className="t-down">{d.device_time_offset > 0 ? "ahead" : "behind"} {Math.round(Math.abs(d.device_time_offset) / 60)} min</span>}</dd>
                <dt>Serial</dt><dd className="mono">{d.serial ?? "—"}</dd>
                <dt>Firmware</dt><dd className="mono small">{d.firmware ?? "—"}</dd>
              </dl>
              {d.last_error && <div className="err">Last pull failed {ago(d.last_pull_try)}: {d.last_error}</div>}
              <div className="dc-foot">
                <Link className="btn sm primary" to={`/devices/${d.id}`}>Manage</Link>
                {admin && <>
                <button className="btn sm ghost" onClick={() => setEdit(d)}>Edit</button>
                <button className="btn sm ghost" disabled={!!quiet || !d.active} onClick={() => pull.mutate([d.id])}>Pull now</button>
                <button className="btn sm ghost" onClick={() => confirm(`Restart ${d.name}? It is unavailable for about a minute.`) && queue({ kind: "restart", device_ids: [d.id] })}>Restart</button>
                </>}
              </div>
            </div>
          );
        })}
      </section>

      {retired.length > 0 && <p><button className="link" onClick={() => setShowRetired(!showRetired)}>{showRetired ? "Hide" : "Show"} {retired.length} retired device{retired.length > 1 ? "s" : ""} (kept for their history)</button></p>}
      {showRetired && <section className="card flush"><table className="tbl"><thead><tr><th>Name</th><th>Serial</th><th className="r">Punches stored</th><th>Last punch</th><th /></tr></thead>
        <tbody>{retired.map((d) => <tr key={d.id}><td>{d.name}</td><td className="mono">{d.serial}</td><td className="r">{num(d.punches_stored)}</td><td>{d.last_punch ?? "—"}</td>
          <td className="r">{admin && <button className="link" onClick={() => setEdit(d)}>Edit</button>}</td></tr>)}</tbody></table></section>}

      <section className="card flush" id="events">
        <div className="card-head pad"><h2>Device history</h2>
          <div className="actions">
            <select value={evDevice} onChange={(e) => { setEvDevice(e.target.value); setEvPage(1); }}><option value="">All devices</option>{current.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select>
            <select value={evKind} onChange={(e) => { setEvKind(e.target.value); setEvPage(1); }}><option value="">All events</option>{Object.entries(EVENT_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
          </div></div>
        {events.data?.rows.length === 0 ? <Empty>No events.</Empty> :
          <table className="tbl"><tbody>{events.data?.rows.map((e) => (
            <tr key={e.id}><td className="mono nowrap">{e.ts}</td><td>{e.device}</td>
              <td><Pill tone={e.kind === "up" || e.kind === "pull_ok_after_error" ? "up" : e.kind.startsWith("device_") || e.kind === "restart" ? "info" : "down"}>{EVENT_LABEL[e.kind] ?? e.kind}</Pill></td>
              <td className="muted">{e.detail}</td><td className="muted r nowrap">{ago(e.ts)}</td></tr>))}</tbody></table>}
        <div className="tbl-foot"><span /><Pager page={evPage} size={50} total={events.data?.total ?? 0} onPage={setEvPage} /></div>
      </section>

      {edit && <DeviceForm dev={edit === "new" ? null : edit} onClose={() => setEdit(null)} onSaved={() => qc.invalidateQueries({ queryKey: ["devices"] })} />}
    </div>
  );
}

function DeviceForm({ dev, onClose, onSaved }: { dev: Device | null; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [f, setF] = useState({
    name: dev?.name ?? "", ip: dev?.ip ?? "", port: dev?.port ?? 4370, commkey: "", location: dev?.location ?? "",
    active: dev ? !!dev.active : true, retired: dev ? !!dev.retired : false,
  });
  const save = useMutation({
    mutationFn: () => {
      const body = { ...f, commkey: f.commkey === "" ? undefined : f.commkey };
      return dev ? api.patch(`/api/devices/${dev.id}`, body) : api.post("/api/devices", body);
    },
    onSuccess: () => { toast("Device saved"); onSaved(); onClose(); },
    onError: (e) => toast((e as Error).message, "error"),
  });
  const set = (k: string, v: unknown) => setF((o) => ({ ...o, [k]: v }));
  return (
    <Modal title={dev ? `Edit ${dev.name}` : "Add device"} onClose={onClose}
      footer={<><button className="btn ghost" onClick={onClose}>Cancel</button><button className="btn primary" disabled={save.isPending} onClick={() => save.mutate()}>Save</button></>}>
      <div className="form two">
        <label className="span2">Name<input value={f.name} onChange={(e) => set("name", e.target.value)} /></label>
        <label>IP address<input value={f.ip} onChange={(e) => set("ip", e.target.value)} className="mono" /></label>
        <label>Port<input type="number" value={f.port} onChange={(e) => set("port", +e.target.value)} /></label>
        <label>Comm key<input type="password" placeholder={dev?.has_commkey ? "unchanged" : "0 if none"} value={f.commkey} onChange={(e) => set("commkey", e.target.value)} /></label>
        <label>Location<input value={f.location} onChange={(e) => set("location", e.target.value)} /></label>
        <label className="check-row"><input type="checkbox" checked={f.active} onChange={(e) => set("active", e.target.checked)} /> Poll this device</label>
        <label className="check-row"><input type="checkbox" checked={f.retired} onChange={(e) => set("retired", e.target.checked)} /> Retired (keep history only)</label>
      </div>
    </Modal>
  );
}
