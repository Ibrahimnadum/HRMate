import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { Modal, Pill, Spinner, useToast } from "../components/ui";
import { JobWatch } from "./DeviceManage";

interface EnrollInfo {
  fingers: number[]; face: boolean; enroll_device_id: number | null;
  devices: { id: number; name: string; active: number; online: number | null; fingers: number | null }[];
}

// ZKTeco finger numbers: 0-4 left hand little to thumb, 5-9 right hand thumb to little
const LEFT = [[0, "Little"], [1, "Ring"], [2, "Middle"], [3, "Index"], [4, "Thumb"]] as const;
const RIGHT = [[5, "Thumb"], [6, "Index"], [7, "Middle"], [8, "Ring"], [9, "Little"]] as const;

/** What the employee has in the backup, with a button to enroll a finger on the enrollment device. */
export function Biometrics({ badge, name, admin }: { badge: string; name: string; admin: boolean }) {
  const [open, setOpen] = useState(false);
  const q = useQuery({ queryKey: ["enroll", badge], queryFn: () => api.get<EnrollInfo>(`/api/enroll/${badge}`) });
  return (
    <div className="bio">
      <div className="card-head"><h4>Fingerprints and face</h4>
        {admin && <button className="btn sm primary" onClick={() => setOpen(true)}>+ Enroll a finger</button>}</div>
      {!q.data ? <Spinner /> : <>
        <p className="small">
          Backup: <b>{q.data.fingers.length}</b> finger{q.data.fingers.length === 1 ? "" : "s"}{q.data.fingers.length ? ` (${q.data.fingers.map(fingerName).join(", ")})` : ""}
          {" · "}face {q.data.face ? <Pill tone="up">saved</Pill> : <Pill tone="muted">none</Pill>}
        </p>
        <div className="bio-devs">{q.data.devices.filter((d) => d.active).map((d) => (
          <span key={d.id} className={`chip ${d.fingers != null ? "on" : ""}`} title={d.fingers != null ? `${d.fingers} finger(s) on ${d.name}` : `Not on ${d.name}`}>
            {d.name}{d.fingers != null ? ` · ${d.fingers}` : " · —"}</span>))}
        </div>
      </>}
      {open && q.data && <EnrollDialog badge={badge} name={name} info={q.data} onClose={() => setOpen(false)} />}
    </div>
  );
}

export function fingerName(f: number) {
  const l = f < 5 ? LEFT.find((x) => x[0] === f) : RIGHT.find((x) => x[0] === f);
  return `${f < 5 ? "left" : "right"} ${l?.[1].toLowerCase()}`;
}

function EnrollDialog({ badge, name, info, onClose }: { badge: string; name: string; info: EnrollInfo; onClose: () => void }) {
  const toast = useToast();
  const qc = useQueryClient();
  const enrollDev = info.devices.find((d) => d.id === info.enroll_device_id);
  const [finger, setFinger] = useState<number | null>(null);
  const [copyTo, setCopyTo] = useState<number[]>(info.devices.filter((d) => d.active && d.id !== info.enroll_device_id).map((d) => d.id));
  const [job, setJob] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  const go = useMutation({
    mutationFn: () => api.post<{ id: number; waiting_for: string | null }>("/api/enroll", { badge, finger, copy_to: copyTo }),
    onSuccess: (r) => { setFailed(false); setJob(r.id); if (r.waiting_for) toast(`Starts after the board window (${r.waiting_for}).`); },
    onError: (e) => toast((e as Error).message, "error"),
  });
  const hand = (list: readonly (readonly [number, string])[], label: string) => (
    <div className="hand"><span className="muted small">{label}</span>
      <div>{list.map(([f, n]) => (
        <button key={f} className={`finger ${finger === f ? "on" : ""} ${info.fingers.includes(f) ? "has" : ""}`} disabled={!!job} onClick={() => setFinger(f)}
          title={info.fingers.includes(f) ? "Already enrolled; enrolling again replaces it" : ""}>{n}</button>))}</div>
    </div>
  );
  return (
    <Modal title={`Enroll a finger: ${name}`} onClose={onClose}
      footer={job ? (failed
        ? <><button className="link" onClick={() => { setJob(null); setFailed(false); }}>Choose another finger</button>
            <button className="btn ghost" onClick={onClose}>Close</button>
            <button className="btn primary" disabled={go.isPending} onClick={() => go.mutate()}>Try again</button></>
        : <button className="btn primary" onClick={onClose}>Close</button>) :
        <><button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={finger === null || !enrollDev || go.isPending} onClick={() => go.mutate()}>Start on {enrollDev?.name ?? "device"}</button></>}>
      {!enrollDev ? <p className="form-err">Choose the enrollment device in Settings first.</p> : !job ? <>
        <p>The employee goes to <b>{enrollDev.name}</b>. After you press Start, the device asks for the finger; they press it 3 times within a minute.</p>
        <div className="hands">{hand(LEFT, "Left hand")}{hand(RIGHT, "Right hand")}</div>
        <p className="muted small">Fingers with a dot are already enrolled.</p>
        <div className="form"><span className="small"><b>Then copy to</b></span>
          <div className="bio-devs">{info.devices.filter((d) => d.active && d.id !== info.enroll_device_id).map((d) => (
            <label key={d.id} className="check-row"><input type="checkbox" checked={copyTo.includes(d.id)}
              onChange={(e) => setCopyTo(e.target.checked ? [...copyTo, d.id] : copyTo.filter((x) => x !== d.id))} /> {d.name}</label>))}</div>
        </div>
      </> : <JobWatch key={job} id={job} onDone={(j) => {
        setFailed(j.status !== "done");
        qc.invalidateQueries({ queryKey: ["enroll", badge] });
        toast(j.status === "done" ? "Finger enrolled" : "Enrollment did not finish. See the log.", j.status === "done" ? undefined : "error");
      }} />}
    </Modal>
  );
}
