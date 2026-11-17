import { useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { getSale } from "./api";
import { RESULTS_URL } from "./config";
import Icon from "./components/Icon";
import Logo from "./components/Logo";
import Buyer from "./pages/Buyer";
import Dashboard from "./pages/Dashboard";
import { usePoll } from "./usePoll";

function Sidebar({ onNavigate }: { onNavigate: () => void }) {
  const { data: sale } = usePoll(getSale, 3000);
  const mode = sale?.mode;
  return (
    <aside className="sidebar-inner">
      <div className="side-logo"><Logo /></div>
      <nav className="side-nav">
        <NavLink to="/" end onClick={onNavigate}><Icon name="dashboard" /> Dashboard</NavLink>
        <NavLink to="/buy" onClick={onNavigate}><Icon name="bag" /> Buyer view</NavLink>
        <a href={RESULTS_URL} target="_blank" rel="noreferrer"><Icon name="bolt" /> Load tests</a>
      </nav>
      <div className="mode-card">
        <div className="mode-card-label">Mode</div>
        <div className="mode-card-value">
          <span className={`dot ${mode ?? "off"}`} />
          {mode === "safe" ? "Safe" : mode === "naive" ? "Naive" : "No sale"}
        </div>
        <p>{mode === "safe" ? "Atomic reservations prevent overselling."
          : mode === "naive" ? "No locking. Expect oversold units under load."
          : "Create a sale from the dashboard."}</p>
      </div>
    </aside>
  );
}

export default function App() {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  useEffect(() => setOpen(false), [pathname]);

  return (
    <div className="shell">
      <div className="sidebar"><Sidebar onNavigate={() => setOpen(false)} /></div>

      <header className="mobilebar">
        <Logo />
        <button className="menu-btn" onClick={() => setOpen(!open)} aria-label={open ? "Close menu" : "Open menu"} aria-expanded={open}>
          <Icon name={open ? "close" : "menu"} size={22} />
        </button>
      </header>
      {open && (
        <div className="drawer-backdrop" onClick={() => setOpen(false)}>
          <div className="drawer" onClick={(e) => e.stopPropagation()}><Sidebar onNavigate={() => setOpen(false)} /></div>
        </div>
      )}

      <main className="main">
        <div className="main-inner">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/buy" element={<Buyer />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}
