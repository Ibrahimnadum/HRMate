import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

/* ---------- toasts ---------- */
type Toast = { id: number; text: string; kind: "ok" | "error" };
const ToastCtx = createContext<(text: string, kind?: "ok" | "error") => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((text: string, kind: "ok" | "error" = "ok") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, text, kind }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), kind === "error" ? 6000 : 3500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts">{items.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.text}</div>)}</div>
    </ToastCtx.Provider>
  );
}

/* ---------- modal / drawer ---------- */
export function Modal({ title, onClose, children, footer, wide, drawer }: {
  title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean; drawer?: boolean;
}) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className={`overlay ${drawer ? "is-drawer" : ""}`} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`${drawer ? "drawer" : "modal"} ${wide ? "wide" : ""}`} role="dialog">
        <div className="modal-head"><h3>{title}</h3><button className="icon-btn" onClick={onClose} aria-label="Close">✕</button></div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

/* ---------- multi select with search ---------- */
export type Option = { value: string; label: string; hint?: string };
export function MultiSelect({ label, options, value, onChange, placeholder = "All", width }: {
  label: string; options: Option[]; value: string[]; onChange: (v: string[]) => void; placeholder?: string; width?: number;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    const list = s ? options.filter((o) => (o.label + " " + (o.hint ?? "") + " " + o.value).toLowerCase().includes(s)) : options;
    return list.slice(0, 300);
  }, [q, options]);
  const sel = new Set(value);
  const summary = value.length === 0 ? placeholder
    : value.length === 1 ? options.find((o) => o.value === value[0])?.label ?? value[0]
    : `${value.length} selected`;
  const toggle = (v: string) => onChange(sel.has(v) ? value.filter((x) => x !== v) : [...value, v]);
  return (
    <div className="ms" ref={ref} style={{ minWidth: width }}>
      <span className="ms-label">{label}</span>
      <button type="button" className={`ms-btn ${value.length ? "has" : ""}`} onClick={() => setOpen((o) => !o)}>
        <span className="ms-sum">{summary}</span>
        {value.length > 0 && <span className="ms-clear" onClick={(e) => { e.stopPropagation(); onChange([]); }}>✕</span>}
        <span className="caret">▾</span>
      </button>
      {open && (
        <div className="ms-pop">
          {options.length > 8 && <input autoFocus className="ms-search" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} />}
          <div className="ms-actions">
            <button type="button" onClick={() => onChange(Array.from(new Set([...value, ...shown.map((o) => o.value)])))}>Select {q ? "shown" : "all"}</button>
            <button type="button" onClick={() => onChange([])}>Clear</button>
          </div>
          <div className="ms-list">
            {shown.map((o) => (
              <label key={o.value} className="ms-item">
                <input type="checkbox" checked={sel.has(o.value)} onChange={() => toggle(o.value)} />
                <span>{o.label}</span>{o.hint && <em>{o.hint}</em>}
              </label>
            ))}
            {shown.length === 0 && <div className="muted pad">No match</div>}
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------- small pieces ---------- */
export const Pill = ({ tone, children }: { tone: "up" | "down" | "wait" | "quiet" | "info" | "muted"; children: ReactNode }) =>
  <span className={`pill ${tone}`}>{children}</span>;

export function Pager({ page, size, total, onPage }: { page: number; size: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / size));
  return (
    <div className="pager">
      <span className="muted">{total === 0 ? "No rows" : `${((page - 1) * size + 1).toLocaleString()}–${Math.min(page * size, total).toLocaleString()} of ${total.toLocaleString()}`}</span>
      <button className="btn sm ghost" disabled={page <= 1} onClick={() => onPage(1)}>«</button>
      <button className="btn sm ghost" disabled={page <= 1} onClick={() => onPage(page - 1)}>‹ Prev</button>
      <span className="pg">Page {page} / {pages}</span>
      <button className="btn sm ghost" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next ›</button>
      <button className="btn sm ghost" disabled={page >= pages} onClick={() => onPage(pages)}>»</button>
    </div>
  );
}

export function SortTh({ id, sort, dir, onSort, children, className }: {
  id: string; sort: string; dir: "asc" | "desc"; onSort: (id: string) => void; children: ReactNode; className?: string;
}) {
  const on = sort === id;
  return <th className={`sortable ${on ? "on" : ""} ${className ?? ""}`} onClick={() => onSort(id)}>{children}<span className="arrow">{on ? (dir === "asc" ? "▲" : "▼") : "↕"}</span></th>;
}

export function Bars({ series, labels, height = 140, compare, unit = "", every = 1, compareLabel = "last week" }: {
  series: number[]; labels: string[]; height?: number; compare?: number[]; unit?: string; every?: number; compareLabel?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...series, ...(compare ?? []));
  const w = 100 / series.length;
  return (
    <div className="bars" style={{ height }}>
      <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" width="100%" height={height}>
        {series.map((v, i) => {
          const h = (v / max) * (height - 18);
          const c = compare ? (compare[i] / max) * (height - 18) : 0;
          return (
            <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={i * w} y={0} width={w} height={height} fill="transparent" />
              {compare && <rect x={i * w + w * 0.18} y={height - 18 - c} width={w * 0.64} height={c} className="bar-cmp" />}
              <rect x={i * w + w * 0.28} y={height - 18 - h} width={w * 0.44} height={h} rx={0.6} className={`bar ${hover === i ? "hot" : ""}`} />
            </g>
          );
        })}
      </svg>
      <div className="bar-labels">{labels.map((l, i) => <span key={i} style={{ width: `${w}%` }}>{i % every === 0 ? l : ""}</span>)}</div>
      {hover !== null && (
        <div className="bar-tip" style={{ left: `${(hover + 0.5) * w}%` }}>
          <b>{series[hover].toLocaleString()}{unit}</b>{compare && <span> · {compareLabel} {compare[hover].toLocaleString()}</span>}
          <em>{labels[hover] || hover}</em>
        </div>
      )}
    </div>
  );
}

export const Empty = ({ children }: { children: ReactNode }) => <div className="empty">{children}</div>;
export const Spinner = () => <div className="spinner" />;
