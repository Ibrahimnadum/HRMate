import { Fragment, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, Job } from "../api";
import { can, useMe } from "../App";
import { Empty, Pill, Spinner, useToast } from "../components/ui";
import { ago } from "../util";

/** Queue a device job; returns a function. Shows a toast with a link to the Jobs tab. */
export function useQueueJob() {
  const toast = useToast();
  const qc = useQueryClient();
  const nav = useNavigate();
  const m = useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post<{ id: number; waiting_for: string | null }>("/api/jobs", body),
    onSuccess: (r) => {
      toast(r.waiting_for ? `Queued. It starts after the board window (${r.waiting_for}).` : "Queued. Follow it on the Jobs tab.");
      qc.invalidateQueries({ queryKey: ["jobs"] });
      nav("/devices/jobs");
    },
    onError: (e) => toast((e as Error).message, "error"),
  });
  return (body: Record<string, unknown>) => m.mutate(body);
}

const TONE: Record<Job["status"], "up" | "down" | "wait" | "info" | "muted"> = { done: "up", failed: "down", running: "info", queued: "wait", cancelled: "muted" };

export default function Jobs() {
  const me = useMe();
  const toast = useToast();
  const qc = useQueryClient();
  const [open, setOpen] = useState<number | null>(null);
  const q = useQuery({
    queryKey: ["jobs"], queryFn: () => api.get<{ rows: Job[]; quiet_until: string | null }>("/api/jobs"),
    refetchInterval: (query) => (query.state.data?.rows.some((j) => j.status === "running" || j.status === "queued") ? 2000 : 15000),
  });
  const cancel = useMutation({
    mutationFn: (id: number) => api.post(`/api/jobs/${id}/cancel`),
    onSuccess: () => { toast("Cancelled"); qc.invalidateQueries({ queryKey: ["jobs"] }); },
    onError: (e) => toast((e as Error).message, "error"),
  });
  if (!q.data) return <Spinner />;
  const active = q.data.rows.find((j) => j.status === "running");
  return (
    <div>
      <p className="muted">Device jobs run one at a time, between log pulls, and never inside an Activity Board window: a job that meets a window waits and continues after it. Every nightly scan also backs up all fingerprints.</p>
      {q.data.quiet_until && <div className="banner quiet"><b>Board window until {q.data.quiet_until}.</b> Queued jobs start after it.</div>}
      <section className="card flush">
        {q.data.rows.length === 0 ? <Empty>No jobs yet.</Empty> :
          <table className="tbl">
            <thead><tr><th>#</th><th>Job</th><th>Status</th><th>Progress</th><th>By</th><th>Queued</th><th /></tr></thead>
            <tbody>{q.data.rows.map((j) => (<Fragment key={j.id}>
              <tr className={open === j.id ? "sel" : ""} onClick={() => setOpen(open === j.id ? null : j.id)} style={{ cursor: "pointer" }}>
                <td className="mono muted">{j.id}</td>
                <td><b>{j.title}</b></td>
                <td><Pill tone={TONE[j.status]}>{j.status}</Pill></td>
                <td style={{ width: 160 }}><span className="mini-meter wide"><i style={{ width: `${j.status === "done" ? 100 : j.progress}%` }} className={j.status === "failed" ? "bad" : ""} /></span></td>
                <td>{j.created_by}</td>
                <td className="muted nowrap">{ago(j.created_at)}</td>
                <td className="r">{j.status === "queued" && can(me, "admin") && <button className="link danger" onClick={(e) => { e.stopPropagation(); cancel.mutate(j.id); }}>Cancel</button>}</td>
              </tr>
              {(open === j.id || (active?.id === j.id && open === null)) && <tr><td colSpan={7} className="log-cell"><pre className="job-log">{j.log || "Waiting to start…"}</pre></td></tr>}
            </Fragment>))}</tbody>
          </table>}
      </section>
    </div>
  );
}
