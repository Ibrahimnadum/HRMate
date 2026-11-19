import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, Department, DeviceUserRow } from "../api";
import { can, useMe } from "../App";
import { Empty, Modal, MultiSelect, Spinner } from "../components/ui";
import { ago, normNo } from "../util";
import { useQueueJob } from "./Jobs";

interface MapData {
  devices: { id: number; name: string; ip: string; active: number; last_scan_at: string | null; users_on_device: number | null; fingers_on_device: number | null; faces_on_device: number | null }[];
  rows: DeviceUserRow[]; enroll_device_id: number | null;
}
type View = "active" | "missing" | "resigned" | "unknown" | "names" | "nofinger" | "all";
const VIEWS: [View, string][] = [["active", "Active employees"], ["missing", "Missing on a device"], ["resigned", "Inactive, still on devices"],
  ["unknown", "On devices, not in system"], ["names", "Name differs"], ["nofinger", "No fingerprint"], ["all", "Everyone"]];

export default function DeviceUsers() {
  const me = useMe();
  const admin = can(me, "admin");
  const queue = useQueueJob();
  const map = useQuery({ queryKey: ["device-users"], queryFn: () => api.get<MapData>("/api/device-users") });
  const deps = useQuery({ queryKey: ["departments"], queryFn: () => api.get<{ rows: Department[] }>("/api/departments") });
  const [view, setView] = useState<View>("active");
  const [q, setQ] = useState("");
  const [dep, setDep] = useState<string[]>([]);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [dialog, setDialog] = useState<"copy" | "remove" | null>(null);

  const devices = useMemo(() => (map.data?.devices ?? []).filter((d) => d.active), [map.data]);
  const ids = devices.map((d) => String(d.id));
  const scanned = devices.filter((d) => d.last_scan_at);

  const rows = useMemo(() => {
    const s = q.trim().toLowerCase();
    const depNames = new Set(dep.map((d) => d === "none" ? "" : deps.data?.rows.find((x) => String(x.id) === d)?.name ?? ""));
    return (map.data?.rows ?? []).filter((r) => {
      const present = ids.filter((i) => r.on[i]);
      const onSomething = present.length > 0;
      if (s && !(r.name.toLowerCase().includes(s) || (/^\d+$/.test(s) && normNo(r.emp_no) === normNo(s)) || (s.startsWith("#") && r.badge === s.slice(1)))) return false;
      if (dep.length && !depNames.has(r.department ?? "")) return false;
      switch (view) {
        case "active": return r.active === 1;
        case "missing": return r.active === 1 && onSomething && present.length < scanned.length;
        case "resigned": return r.active === 0 && onSomething;
        case "unknown": return !!r.unknown;
        case "names": return present.some((i) => r.on[i].name && r.name && r.on[i].name !== r.name.trim().slice(0, 24));
        case "nofinger": return r.active === 1 && onSomething && present.every((i) => r.on[i].fingers === 0);
        default: return true;
      }
    }).sort((a, b) => (+normNo(a.emp_no || "999999") - +normNo(b.emp_no || "999999")) || (+a.badge - +b.badge));
  }, [map.data, q, dep, view, ids.join(), scanned.length, deps.data]); // eslint-disable-line

  if (!map.data) return <Spinner />;
  const allOn = rows.length > 0 && rows.every((r) => sel.has(r.badge));
  const selRows = (map.data.rows).filter((r) => sel.has(r.badge));
  const depOpts = [...(deps.data?.rows ?? []).map((d) => ({ value: String(d.id), label: d.name })), { value: "none", label: "No department" }];
  const lastScan = scanned.map((d) => d.last_scan_at!).sort()[0];
  return (
    <div>
      <div className="sub-head">
        <p className="muted">{scanned.length < devices.length ? `${devices.length - scanned.length} device(s) not read yet. ` : ""}
          {lastScan ? `Read ${ago(lastScan)} — refreshed every night and after each change.` : "Devices have not been read yet: run Read devices now."}</p>
        {admin && <div className="actions">
          <button className="btn ghost" onClick={() => queue({ kind: "push_names", badges: [] })} title="Write the names from this system (max 24 characters) to every device">✎ Write all names to devices</button>
          <button className="btn primary" onClick={() => queue({ kind: "scan" })}>⟳ Read devices now</button>
        </div>}
      </div>

      <section className="filters card">
        <div className="frow">
          <div className="field grow"><span className="ms-label">Search</span><input placeholder="Name or employee no. · #12 for device ID" value={q} onChange={(e) => setQ(e.target.value)} /></div>
          <MultiSelect label="Departments" options={depOpts} value={dep} onChange={setDep} />
        </div>
        <div className="chips">{VIEWS.map(([v, l]) => <button key={v} className={`chip ${view === v ? "on" : ""}`} onClick={() => { setView(v); setSel(new Set()); }}>{l}</button>)}</div>
      </section>

      {admin && sel.size > 0 && (
        <div className="bulkbar">
          <b>{sel.size} selected</b>
          <button className="btn sm ghost" onClick={() => setDialog("copy")}>⇄ Copy to devices</button>
          <button className="btn sm ghost" onClick={() => queue({ kind: "push_names", badges: [...sel] })}>✎ Write names</button>
          <button className="btn sm ghost" onClick={() => setDialog("remove")}>✕ Remove from devices</button>
          <button className="link" onClick={() => setSel(new Set())}>Clear selection</button>
        </div>
      )}

      <section className="card flush">
        <div className="tbl-wrap">
          <table className="tbl map">
            <thead><tr>
              {admin && <th className="cb"><input type="checkbox" checked={allOn} onChange={() => setSel(allOn ? new Set() : new Set(rows.map((r) => r.badge)))} /></th>}
              <th>Emp No.</th><th>Name</th><th>Device ID</th><th>Dept</th>
              {devices.map((d) => <th key={d.id} className="c" title={`${d.ip} · ${d.users_on_device ?? "?"} users, ${d.fingers_on_device ?? "?"} fingerprints, ${d.faces_on_device ?? "?"} faces`}>
                {d.name}{map.data!.enroll_device_id === d.id && <span className="enroll" title="Enrollment device">★</span>}</th>)}
              <th className="c" title="Fingerprints kept in this system's backup">Backup</th>
            </tr></thead>
            <tbody>{rows.slice(0, 600).map((r) => {
              const present = ids.filter((i) => r.on[i]).length;
              return (
                <tr key={r.badge} className={sel.has(r.badge) ? "sel" : r.unknown ? "unknown" : r.active === 0 ? "inactive" : ""}>
                  {admin && <td className="cb"><input type="checkbox" checked={sel.has(r.badge)} onChange={() => { const n = new Set(sel); n.has(r.badge) ? n.delete(r.badge) : n.add(r.badge); setSel(n); }} /></td>}
                  <td className="mono strong">{r.emp_no || <span className="muted">—</span>}</td>
                  <td><b>{r.name || "no name"}</b>{r.unknown && <span className="pill down" style={{ marginLeft: 6 }}>not in system</span>}{r.active === 0 && <span className="pill muted" style={{ marginLeft: 6 }}>inactive</span>}</td>
                  <td className="mono muted">{r.badge}</td>
                  <td className="muted">{r.department ?? ""}</td>
                  {devices.map((d) => {
                    const c = r.on[String(d.id)];
                    if (!d.last_scan_at) return <td key={d.id} className="c muted">?</td>;
                    if (!c) return <td key={d.id} className={`c miss ${r.active === 1 && present > 0 ? "bad" : ""}`}>—</td>;
                    const nameDiff = r.name && c.name !== r.name.trim().slice(0, 24);
                    return (
                      <td key={d.id} className="c has" title={`On device as "${c.name}"${c.admin ? " · device admin" : ""}${c.card ? " · card" : ""}${c.password ? " · password" : ""}${c.face ? " · face" : ""}`}>
                        <span className={`fp ${c.fingers ? "" : "zero"}`}>{c.fingers}F</span>{c.face && <span className="ic face">☺</span>}
                        {c.card && <span className="ic">▭</span>}{c.admin && <span className="ic adm">A</span>}{nameDiff && <span className="ic warn">≠</span>}
                      </td>
                    );
                  })}
                  <td className="c muted">{r.backup_fingers ? `${r.backup_fingers}F` : ""}{r.backup_face ? " ☺" : ""}</td>
                </tr>
              );
            })}</tbody>
          </table>
          {rows.length === 0 && <Empty>Nothing in this view.</Empty>}
          {rows.length > 600 && <div className="muted pad">Showing the first 600; narrow the filters.</div>}
        </div>
        <div className="tbl-foot"><span className="muted small">F = fingerprints on that device · ▭ card · A device admin · ≠ name on device differs · — missing (red when the employee is on another device)</span><span className="muted">{rows.length} rows</span></div>
      </section>

      {dialog === "copy" && <CopyDialog rows={selRows} devices={devices} enroll={map.data.enroll_device_id} onClose={() => setDialog(null)}
        onGo={(source, targets) => { setDialog(null); setSel(new Set()); queue({ kind: "copy", badges: selRows.map((r) => r.badge), source, targets }); }} />}
      {dialog === "remove" && <RemoveDialog rows={selRows} devices={devices} onClose={() => setDialog(null)}
        onGo={(ids, deactivate) => { setDialog(null); setSel(new Set()); queue({ kind: "remove", badges: selRows.map((r) => r.badge), device_ids: ids, deactivate }); }} />}
    </div>
  );
}

function CopyDialog({ rows, devices, enroll, onClose, onGo }: {
  rows: DeviceUserRow[]; devices: MapData["devices"]; enroll: number | null; onClose: () => void; onGo: (source: string, targets: number[]) => void;
}) {
  // default source: the enrollment device if everyone selected is on it, otherwise the device holding the most fingerprints
  const best = (() => {
    if (enroll && rows.every((r) => r.on[String(enroll)])) return String(enroll);
    let top = "", n = -1;
    devices.forEach((d) => { const s = rows.reduce((a, r) => a + (r.on[String(d.id)]?.fingers ?? -100), 0); if (s > n) { n = s; top = String(d.id); } });
    return top;
  })();
  const [source, setSource] = useState(best);
  const [targets, setTargets] = useState<string[]>([]);
  const missing = source !== "backup" ? rows.filter((r) => !r.on[source]) : rows.filter((r) => !r.backup_fingers);
  return (
    <Modal title={`Copy ${rows.length} employee${rows.length > 1 ? "s" : ""} to devices`} onClose={onClose}
      footer={<><button className="btn ghost" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!targets.length} onClick={() => onGo(source, targets.filter((t) => t !== source).map(Number))}>Copy</button></>}>
      <p className="muted">Copies the user record, fingerprints, face, card and password. The name written is the one in this system. Faces go only to devices with the same face version.</p>
      <div className="form">
        <label>Copy from<select value={source} onChange={(e) => { setSource(e.target.value); setTargets((t) => t.filter((x) => x !== e.target.value)); }}>
          {devices.map((d) => <option key={d.id} value={d.id}>{d.name}{enroll === d.id ? " (enrollment device)" : ""}</option>)}
          <option value="backup">This system's backup</option>
        </select></label>
        {missing.length > 0 && <div className="form-err">{missing.length} of the selected {source === "backup" ? "have no fingerprints in the backup" : "are not on that device"} and will be skipped: {missing.slice(0, 6).map((r) => r.name || r.badge).join(", ")}{missing.length > 6 ? "…" : ""}</div>}
        <MultiSelect label="To devices" options={devices.filter((d) => String(d.id) !== source).map((d) => ({ value: String(d.id), label: d.name, hint: d.ip }))} value={targets} onChange={setTargets} placeholder="Choose…" />
      </div>
    </Modal>
  );
}

function RemoveDialog({ rows, devices, onClose, onGo }: { rows: DeviceUserRow[]; devices: MapData["devices"]; onClose: () => void; onGo: (ids: number[], deactivate: boolean) => void }) {
  const [ids, setIds] = useState<string[]>(devices.map((d) => String(d.id)));
  const [deactivate, setDeactivate] = useState(rows.every((r) => r.active !== 0));
  const [typed, setTyped] = useState("");
  return (
    <Modal title={`Remove ${rows.length} employee${rows.length > 1 ? "s" : ""} from devices`} onClose={onClose}
      footer={<><button className="btn ghost" onClick={onClose}>Cancel</button><button className="btn danger" disabled={!ids.length || typed !== "REMOVE"} onClick={() => onGo(ids.map(Number), deactivate)}>Remove</button></>}>
      <p>{rows.slice(0, 8).map((r) => r.name || r.badge).join(", ")}{rows.length > 8 ? ` and ${rows.length - 8} more` : ""}</p>
      <p className="muted">Their user record and fingerprints are backed up first, so they can be put back later with Copy → from backup. Their punches stay in this system.</p>
      <div className="form">
        <MultiSelect label="From devices" options={devices.map((d) => ({ value: String(d.id), label: d.name, hint: d.ip }))} value={ids} onChange={setIds} placeholder="Choose…" />
        <label className="check-row"><input type="checkbox" checked={deactivate} onChange={(e) => setDeactivate(e.target.checked)} /> Also mark them inactive (resigned)</label>
        <label>Type REMOVE to confirm<input value={typed} onChange={(e) => setTyped(e.target.value)} /></label>
      </div>
    </Modal>
  );
}
