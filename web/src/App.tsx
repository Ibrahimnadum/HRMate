import { createContext, useContext, useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import Icon from "./components/Icon";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, Me, setCsrf, Settings } from "./api";
import Login from "./pages/Login";
import Overview from "./pages/Overview";
import Punches from "./pages/Punches";
import Employees from "./pages/Employees";
import Devices from "./pages/Devices";
import SettingsPage from "./pages/Settings";
import { Spinner } from "./components/ui";

const MeCtx = createContext<Me | null>(null);
export const useMe = () => useContext(MeCtx)!;
export const can = (me: Me, ...roles: Me["role"][]) => roles.includes(me.role);

export default function App() {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const qc = useQueryClient();
  useEffect(() => {
    api.get<Me>("/api/me").then((m) => { setCsrf(m.csrf); setMe(m); }).catch(() => setMe(null));
    const lost = () => { qc.clear(); setMe(null); };
    window.addEventListener("auth:lost", lost);
    return () => window.removeEventListener("auth:lost", lost);
  }, [qc]);

  if (me === undefined) return <div className="boot"><Spinner /></div>;
  if (!me) return <Login onIn={(m) => { setCsrf(m.csrf); setMe(m); }} />;
  return (
    <MeCtx.Provider value={me}>
      <Shell onOut={() => { api.post("/api/logout").finally(() => { qc.clear(); setMe(null); }); }} />
    </MeCtx.Provider>
  );
}

const NAV = [
  { to: "/", label: "Overview", icon: "grid" },
  { to: "/punches", label: "Punches", icon: "finger" },
  { to: "/employees", label: "Employees", icon: "users" },
  { to: "/devices", label: "Devices", icon: "device" },
  { to: "/settings", label: "Settings", icon: "cog" },
];

function Shell({ onOut }: { onOut: () => void }) {
  const me = useMe();
  const loc = useLocation();
  const nav = useNavigate();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api.get<Settings>("/api/settings"), refetchInterval: 60_000 });
  const quiet = settings.data?.quiet_now;
  const [q, setQ] = useState("");
  useEffect(() => { window.scrollTo(0, 0); }, [loc.pathname]);
  const initials = me.display_name.split(/\s+/).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
  return (
    <div className="frame">
      <div className="app">
        <header className="topbar">
          <div className="logo"><span className="logo-mark"><Icon name="helmet" color="#fff" stroke={1.8} /></span><span>IRATEC<em>.attendance</em></span></div>
          <form className="search" onSubmit={(e) => { e.preventDefault(); if (q.trim()) nav(`/employees?q=${encodeURIComponent(q.trim())}`); }}>
            <Icon name="search" size={18} color="#5E6878" />
            <input aria-label="Search employees" placeholder="Search name or employee no." value={q} onChange={(e) => setQ(e.target.value)} />
          </form>
          <span className="grow" />
          {quiet
            ? <span className="status-pill quiet" title="The Activity Board owns the devices. No pulls or checks until the window ends.">Board window until {quiet}</span>
            : <span className="status-pill live"><i />Collecting</span>}
          <NavLink to="/settings" className="top-link">Settings</NavLink>
          <div className="me"><span>{me.display_name}</span><span className="avatar">{initials}</span></div>
        </header>
        <div className="body">
          <nav className="rail">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.to === "/"} className={({ isActive }) => (isActive ? "on" : "")}>
                <Icon name={n.icon} size={22} /><span>{n.label}</span>
              </NavLink>
            ))}
            <span className="grow" />
            <button className="rail-out" onClick={onOut}><Icon name="logout" size={22} /><span>Sign out</span></button>
          </nav>
          <main className="content">
            <Routes>
              <Route path="/" element={<Overview />} />
              <Route path="/punches" element={<Punches />} />
              <Route path="/employees" element={<Employees />} />
              <Route path="/devices/*" element={<Devices />} />
              <Route path="/settings/*" element={<SettingsPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </main>
        </div>
      </div>
    </div>
  );
}
