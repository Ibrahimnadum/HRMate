export type Role = "admin" | "hr" | "viewer";
export interface Me { username: string; role: Role; display_name: string; csrf: string }

let csrf = "";
export const setCsrf = (t: string) => { csrf = t; };

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

async function call<T>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    credentials: "same-origin",
    headers: { ...(body !== undefined ? { "Content-Type": "application/json" } : {}), ...(method !== "GET" ? { "X-CSRF": csrf } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) {
    if (res.status === 401 && !url.endsWith("/login")) window.dispatchEvent(new Event("auth:lost"));
    throw new ApiError(data?.error ?? `Request failed (${res.status})`, res.status);
  }
  return data as T;
}

export const api = {
  get: <T,>(url: string) => call<T>("GET", url),
  post: <T,>(url: string, body?: unknown) => call<T>("POST", url, body ?? {}),
  put: <T,>(url: string, body: unknown) => call<T>("PUT", url, body),
  patch: <T,>(url: string, body: unknown) => call<T>("PATCH", url, body),
  del: <T,>(url: string) => call<T>("DELETE", url),
};

export function qs(params: Record<string, string | number | undefined | null | (string | number)[]>) {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) v.forEach((x) => u.append(k, String(x)));
    else u.append(k, String(v));
  }
  return u.toString();
}

/* ---------- shared types ---------- */
export interface Device {
  id: number; serial: string | null; name: string; ip: string | null; port: number; model: string; location: string;
  active: number; retired: number; firmware: string | null; online: number | null; status_since: string | null;
  last_check_at: string | null; last_pull_at: string | null; last_pull_try: string | null; last_error: string | null;
  records_on_device: number | null; users_on_device: number | null; device_time_offset: number | null;
  fingers_on_device?: number | null; faces_on_device?: number | null; users_cap?: number | null; fingers_cap?: number | null;
  faces_cap?: number | null; last_scan_at?: string | null;
  drops_7d?: number; punches_today?: number; punches_stored?: number; last_punch?: string | null; has_commkey?: boolean;
}
export interface Punch {
  id: number; badge: string; ts: string; source: "device" | "legacy" | "manual"; state: number | null; note: string | null;
  created_by: string | null; device_id: number | null; name: string; emp_no: string; employee_id: number | null; department: string; device: string | null;
}
export interface Employee {
  id: number; badge: string; emp_no: string; phone: string; name: string; department_id: number | null; department: string | null; title: string;
  gender: string; card: string; active: number; note: string; device_name: string; last_punch: string | null; days_30: number;
}
export interface Department { id: number; name: string; employees: number }
export interface EventRow { id: number; device_id: number | null; device: string | null; ts: string; kind: string; detail: string | null }
export interface CollectorState { quiet_until: string | null; last_cycle: string | null; next_pull: string | null }
export interface Settings {
  quiet_windows: [string, string][]; work_start: string; work_end: string; grace_minutes: number; weekend: number[];
  quiet_now: string | null; enroll_device_id: number | null; maintenance_time: string; clock_sync: boolean;
}
export interface Job {
  id: number; kind: string; title: string; status: "queued" | "running" | "done" | "failed" | "cancelled"; progress: number;
  log: string; created_by: string; created_at: string; started_at: string | null; finished_at: string | null;
}
export interface Cell { fingers: number; name: string; admin: boolean; card: boolean; password: boolean; face?: boolean }
export interface DeviceUserRow {
  id: number | null; badge: string; emp_no: string; name: string; active: number | null; department: string | null;
  last_punch: string | null; on: Record<string, Cell>; backup_fingers: number; backup_face?: boolean; unknown?: boolean;
}
