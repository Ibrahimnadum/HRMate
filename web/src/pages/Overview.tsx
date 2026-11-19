import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, CollectorState, Device, EventRow } from "../api";
import Icon from "../components/Icon";
import { Empty, Spinner } from "../components/ui";
import { ago, fmtTime, num, parseTs, STATE_LABEL } from "../util";

interface OverviewData {
  devices: Device[]; today: { punches: number; people: number; active_employees: number };
  hourly: { today: number[]; last_week: number[] }; trend: { date: string; people: number }[];
  latest: { id: number; badge: string; emp_no: string | null; ts: string; source: string; name: string; department: string; device: string | null; state?: number | null }[];
  events: EventRow[]; by_department: { department: string; present: number; total: number }[];
  collector: CollectorState; now: string;
}

export const deviceTone = (d: Device, quiet: string | null) =>
  quiet ? "quiet" : d.online === 1 ? "up" : d.online === 0 ? "down" : "wait";
const TONE_TEXT = { up: "Online", down: "Offline", wait: "Checking", quiet: "Board window" } as const;

const initials = (n: string) => n.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?";

export default function Overview() {
  const { data, isLoading } = useQuery({ queryKey: ["overview"], queryFn: () => api.get<OverviewData>("/api/overview"), refetchInterval: 20_000 });
  const [devIdx, setDevIdx] = useState(0);
  const [range, setRange] = useState<"day" | "trend">("day");
  const [hover, setHover] = useState<number | null>(null);
  const [month, setMonth] = useState(() => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), 1); });

  const cal = useMemo(() => {
    const first = new Date(month);
    const lead = (first.getDay() + 6) % 7;
    const days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
    const prevDays = new Date(month.getFullYear(), month.getMonth(), 0).getDate();
    const cells: { d: number; out: boolean; today: boolean }[] = [];
    const t = new Date();
    for (let i = lead; i > 0; i--) cells.push({ d: prevDays - i + 1, out: true, today: false });
    for (let d = 1; d <= days; d++) cells.push({ d, out: false, today: t.getFullYear() === month.getFullYear() && t.getMonth() === month.getMonth() && t.getDate() === d });
    while (cells.length % 7) cells.push({ d: cells.length - lead - days + 1, out: true, today: false });
    return cells;
  }, [month]);

  if (isLoading || !data) return <Spinner />;
  const quiet = data.collector.quiet_until;
  const devices = data.devices.filter((d) => d.active);
  const dev = devices.length ? devices[((devIdx % devices.length) + devices.length) % devices.length] : null;
  const online = devices.filter((d) => d.online === 1).length;
  const pct = data.today.active_employees ? Math.round((data.today.people / data.today.active_employees) * 100) : 0;
  const yesterdayPeople = data.trend.length > 1 ? data.trend[data.trend.length - 8]?.people ?? 0 : 0;
  const diff = data.today.people - yesterdayPeople;

  // chart: punches by hour (05-22) or people per day (14 days)
  const hours = Array.from({ length: 18 }, (_, i) => i + 5);
  const series = range === "day"
    ? hours.map((h) => ({ label: `${String(h).padStart(2, "0")}`, a: data.hourly.last_week[h], b: data.hourly.today[h], tip: `${String(h).padStart(2, "0")}:00 · today ${data.hourly.today[h]} · last week ${data.hourly.last_week[h]}` }))
    : data.trend.map((t) => ({ label: parseTs(t.date + " 00:00:00").toLocaleDateString("en-GB", { day: "2-digit" }), a: 0, b: t.people, tip: `${parseTs(t.date + " 00:00:00").toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })} · ${t.people} people` }));
  const max = Math.max(4, ...series.map((s) => Math.max(s.a, s.b)));
  const step = Math.ceil(max / 4);
  const top = step * 4;

  return (
    <div className="page">
      <header className="page-head">
        <div className="head-left"><span className="title-ic"><Icon name="grid" size={22} /></span><h1>Overview</h1></div>
        <div className="actions">
          <Link className="ic-btn" to="/punches" aria-label="Search punches"><Icon name="search" size={18} color="#141B2D" /></Link>
          <span className="ic-btn blue"><Icon name="calendar" size={20} color="#fff" /></span>
          <span className="date-chip">{parseTs(data.now).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" })}</span>
        </div>
      </header>

      {quiet && <div className="banner quiet"><b>Activity Board window until {quiet}.</b> The devices are left alone during movement times; punches made now are collected right after.</div>}

      <section className="well ov-grid">
        <div className="ov-col">
          <div className="dev-hero">
            <div className="dev-hero-top">
              <button className="round-btn" aria-label="Previous device" onClick={() => setDevIdx((i) => i - 1)}><Icon name="left" size={16} /></button>
              <div><span style={{ fontSize: 13 }}>Devices online</span><b>{quiet ? "—" : `${online} / ${devices.length}`}</b></div>
              <button className="round-btn" aria-label="Next device" onClick={() => setDevIdx((i) => i + 1)}><Icon name="right" size={16} /></button>
            </div>
            {dev && (() => {
              const tone = deviceTone(dev, quiet);
              return (
                <Link to="/devices" className="dev-slab" style={{ textDecoration: "none" }}>
                  <div className="top"><span>{dev.model || "ZKTeco"}</span><span className={`st-${tone}`}>● {TONE_TEXT[tone]}</span></div>
                  <div className="nm">{dev.name}</div>
                  <div className="ln">{dev.ip} · {num(dev.punches_today)} today</div>
                  <div className="sl-ft">{dev.last_error ? <span className="st-down">Pull failing</span> : `Pulled ${ago(dev.last_pull_at)}`}{dev.device_time_offset != null && Math.abs(dev.device_time_offset) < 60 ? " · clock in sync" : ""}</div>
                  <div className="sl-ft">{dev.drops_7d ? `${dev.drops_7d} drop${dev.drops_7d > 1 ? "s" : ""} in 7 days` : "No drops in 7 days"}</div>
                </Link>
              );
            })()}
          </div>

          <div className="card stat-card">
            <div className="hd">Present today<Link className="round-btn" to="/employees" aria-label="Employees"><Icon name="users" size={16} color="#2A4C9B" /></Link></div>
            <div className="big">{num(data.today.people)} <small>/ {num(data.today.active_employees)}</small></div>
            <div className="bar-meter"><i style={{ width: `${Math.min(pct, 100)}%` }} /></div>
            <div className="sl-ft"><span className="dot-ic" style={{ background: diff >= 0 ? "#2A4C9B" : "#E07B39" }}><Icon name={diff >= 0 ? "up" : "down"} size={12} color="#fff" stroke={2.4} /></span>
              {diff === 0 ? "Same as" : `${diff > 0 ? "+" : ""}${diff} compared with`} the same day last week</div>
          </div>

          <div className="card stat-card">
            <div className="hd">Punches today<Link className="round-btn" to="/punches" aria-label="Punches"><Icon name="finger" size={16} color="#2A4C9B" /></Link></div>
            <div className="big">{num(data.today.punches)} <small>punches</small></div>
            <div className="sl-ft"><span className="dot-ic"><Icon name="clock" size={12} color="#fff" stroke={2.2} /></span>
              {quiet ? `Next pull after ${quiet}` : data.collector.next_pull ? `Next pull at ${fmtTime(data.collector.next_pull)}` : "Pulled every 10 minutes"}</div>
          </div>
        </div>

        <div className="ov-col">
          <div className="card">
            <div className="actions" style={{ marginBottom: 18, gap: 18 }}>
              <h2>{range === "day" ? "Punches by hour" : "People present, last 14 days"}</h2>
              {range === "day" && <><span className="legend2"><i style={{ background: "#14213F" }} />Same day last week</span><span className="legend2"><i style={{ background: "#2A4C9B" }} />Today</span></>}
              <span className="grow" />
              <div className="seg"><button className={range === "day" ? "on" : ""} onClick={() => setRange("day")}>Day</button><button className={range === "trend" ? "on" : ""} onClick={() => setRange("trend")}>14 days</button></div>
            </div>
            <div className="pair-chart">
              <div className="pair-axis">{[4, 3, 2, 1, 0].map((k) => <span key={k}>{k * step}</span>)}</div>
              <div className="pair-cols">
                {series.map((s, i) => (
                  <div key={i} className="pair-col" onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
                    {hover === i && <div className="pair-tip">{s.tip}</div>}
                    <div className="bars2">
                      {range === "day" && <i className="a" style={{ height: Math.round((s.a / top) * 200) + 3 }} />}
                      <i className="b" style={{ height: Math.round((s.b / top) * 200) + 3, width: range === "day" ? undefined : 18 }} />
                    </div>
                    <span>{s.label}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="ov-bottom">
            <div className="card" style={{ margin: 0 }}>
              <div className="actions" style={{ marginBottom: 8 }}><h2>Live punches</h2><span className="grow" /><Link to="/punches" className="btn sm ghost">All punches</Link></div>
              {data.latest.length === 0 ? <Empty>No punches yet today.</Empty> :
                <div className="tbl-wrap"><table className="tbl">
                  <thead><tr><th>Name</th><th>Time</th><th>Device</th><th>State</th></tr></thead>
                  <tbody>{data.latest.slice(0, 8).map((p) => (
                    <tr key={p.id}>
                      <td><div className="person"><span className="initials">{initials(p.name)}</span><div><b>{p.name || "No name"}</b><span>{p.emp_no ? `Emp No. ${p.emp_no}` : `Device ID ${p.badge}`} · {p.department || "—"}</span></div></div></td>
                      <td className="strong nowrap">{fmtTime(p.ts)}<div className="muted small">{ago(p.ts)}</div></td>
                      <td className="muted">{p.device ?? "Manual"}</td>
                      <td className="nowrap"><span className="st-text" style={{ color: p.state === 1 ? "#14213F" : "#2A4C9B" }}>{p.state != null ? STATE_LABEL[p.state] ?? p.state : "Check-In"}</span></td>
                    </tr>))}</tbody>
                </table></div>}
            </div>
            <div className="card" style={{ margin: 0 }}>
              <div className="cal-head">
                <button className="round-btn" aria-label="Previous month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}><Icon name="left" size={16} color="#2A4C9B" /></button>
                <div><b>Calendar</b><span>{month.toLocaleDateString("en-GB", { month: "long", year: "numeric" })}</span></div>
                <button className="round-btn" aria-label="Next month" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}><Icon name="right" size={16} color="#2A4C9B" /></button>
              </div>
              <div className="cal-grid">
                {["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map((w) => <span key={w} className="wd">{w}</span>)}
                {cal.map((c, i) => <span key={i} className={`d ${c.out ? "out" : ""} ${c.today ? "today" : ""}`}>{c.d}</span>)}
              </div>
              <p className="muted small" style={{ margin: "10px 0 0" }}>Holidays and day-offs appear here in Phase 3.</p>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
