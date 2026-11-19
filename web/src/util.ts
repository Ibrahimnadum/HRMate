export const pad = (n: number) => String(n).padStart(2, "0");
export const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export const today = () => iso(new Date());
export const parseTs = (s: string) => new Date(s.replace(" ", "T"));

export function ago(ts: string | null | undefined, now = Date.now()): string {
  if (!ts) return "never";
  const s = Math.round((now - parseTs(ts).getTime()) / 1000);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min ago`;
  const d = Math.floor(s / 86400);
  return d === 1 ? "yesterday" : `${d} days ago`;
}

export const fmtDate = (s: string) =>
  parseTs(s).toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short", year: "numeric" });
export const fmtTime = (s: string) => s.slice(11, 16);
export const num = (n: number | null | undefined) => (n ?? 0).toLocaleString("en-US");
export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export const EVENT_LABEL: Record<string, string> = {
  down: "Went offline", up: "Back online", pull_error: "Pull failed", pull_ok_after_error: "Pull recovered", restart: "Restarted",
  device_restart: "Restarted", device_poweroff: "Powered off", device_voice: "Sound played", device_clear_attlog: "Logs cleared",
  device_clear_oplog: "Super log cleared", device_clear_admin: "Admins cleared", device_initialize: "Initialized", device_moved: "Device swapped",
};
export const STATE_LABEL: Record<number, string> = { 0: "Check-In", 1: "Check-Out", 2: "Break-Out", 3: "Break-In", 4: "OT-In", 5: "OT-Out" };

export type Preset = { label: string; range: () => [string, string] };
export const PRESETS: Preset[] = [
  { label: "Today", range: () => [today(), today()] },
  { label: "Yesterday", range: () => { const d = new Date(); d.setDate(d.getDate() - 1); return [iso(d), iso(d)]; } },
  { label: "Last 7 days", range: () => { const d = new Date(); d.setDate(d.getDate() - 6); return [iso(d), today()]; } },
  { label: "This month", range: () => { const d = new Date(); return [iso(new Date(d.getFullYear(), d.getMonth(), 1)), today()]; } },
  { label: "Last month", range: () => { const d = new Date(); return [iso(new Date(d.getFullYear(), d.getMonth() - 1, 1)), iso(new Date(d.getFullYear(), d.getMonth(), 0))]; } },
  { label: "This year", range: () => [`${new Date().getFullYear()}-01-01`, today()] },
];

/** Employee numbers are compared without leading zeros (0067 = 67). */
export const normNo = (v: string) => (v ?? "").trim().replace(/^0+(?=\d)/, "");
/** "412 · Name" label used in pickers; the device ID is shown as a hint. */
export const empLabel = (e: { emp_no: string; name: string }) => `${e.emp_no || "—"} · ${e.name || "no name"}`;
