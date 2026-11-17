import { useRef, useState } from "react";
import { ApiError, createSale, fmt, getEvents, getStats, Mode, startRush } from "../api";
import ActivityTable from "../components/ActivityTable";
import { LatencyChart, RpsChart } from "../components/Charts";
import KpiCard from "../components/KpiCard";
import { usePoll } from "../usePoll";

export default function Dashboard() {
  const { data: stats, error } = usePoll(getStats, 1000);
  const { data: events } = usePoll(() => getEvents(50), 1000);
  const [stock, setStock] = useState(100);
  const [buyers, setBuyers] = useState(2000);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const activityRef = useRef<HTMLElement>(null);

  const noSale = error instanceof ApiError && error.status === 404;
  const mode: Mode = stats?.mode ?? "safe";
  const rush = stats?.rush;

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setMessage(null);
    try { await action(); } catch (e) { setMessage((e as Error).message); }
    setBusy(false);
  }
  const showActivity = () => activityRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });

  const pct = (n: number, of: number) => (of ? Math.round((n / of) * 100) : 0);
  const sold = stats ? pct(stats.confirmed_orders, stats.initial_stock) : 0;
  const slow = (stats?.avg_latency_ms ?? 0) > 200;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Dashboard</h1>
          <p className="muted">
            {stats ? `${stats.name} · sale #${stats.sale_id} · ${fmt(stats.initial_stock)} units` : "Start a sale to see live numbers."}
          </p>
        </div>
        <div className="tabs" role="group" aria-label="Checkout mode">
          {(["naive", "safe"] as Mode[]).map((m) => (
            <button key={m} className={stats && mode === m ? `tab active ${m}` : "tab"} disabled={busy}
              onClick={() => run(() => createSale(stock, m))}>
              {m === "naive" ? "Naive" : "Safe"}
            </button>
          ))}
        </div>
      </div>

      <section className="panel controls">
        <label>Stock
          <input type="number" min={1} value={stock} onChange={(e) => setStock(Number(e.target.value))} />
        </label>
        <label>Simulated buyers
          <input type="number" min={1} max={20000} value={buyers} onChange={(e) => setBuyers(Number(e.target.value))} />
        </label>
        <div className="control-buttons">
          <button className="btn secondary" disabled={busy} onClick={() => run(() => createSale(stock, mode))}>Reset sale</button>
          <button className="btn primary" disabled={busy || !stats || !!rush?.running} onClick={() => run(() => startRush(buyers))}>
            {rush?.running ? "Rush in progress" : "Start simulated rush"}
          </button>
        </div>
        <p className="muted small controls-note">
          Switching mode or resetting starts a fresh sale with the stock above and stops any rush in progress.
        </p>
        {rush && rush.total > 0 && (
          <div className="rush">
            <div className="rush-head">
              <b>Simulated rush</b>
              <span className="muted small">{fmt(rush.finished)} of {fmt(rush.total)} buyers done</span>
            </div>
            <div className="progress"><div style={{ width: `${pct(rush.finished, rush.total)}%` }} /></div>
            <div className="muted small">
              {fmt(rush.bought)} bought · {fmt(rush.sold_out)} sold out · {fmt(rush.abandoned)} abandoned{rush.errors ? ` · ${fmt(rush.errors)} errors` : ""}
            </div>
          </div>
        )}
        {message && <p className="error-text controls-note">{message}</p>}
      </section>

      {noSale && <div className="panel empty">No sale yet. Choose <b>Naive</b> or <b>Safe</b> above to start one.</div>}

      {stats && (
        <>
          <section className="kpis" aria-label="Key numbers">
            <KpiCard icon="box" tint="purple" value={stats.stock_left} label="Stock left" onOpen={showActivity}
              chip={`${pct(stats.stock_left, stats.initial_stock)}% remaining`} chipTone="neutral" />
            <KpiCard icon="users" tint="amber" value={stats.queue_length} label="Queue length" onOpen={showActivity}
              chip={mode === "naive" ? "No queue in naive" : stats.queue_length ? "Waiting room" : "Empty"} chipTone="neutral" />
            <KpiCard icon="clock" tint="teal" value={stats.active_reservations} label="Active reservations" onOpen={showActivity}
              chip={mode === "naive" ? "No holds in naive" : "Held, unpaid"} chipTone="neutral" />
            <KpiCard icon="check" tint="green" value={stats.confirmed_orders} label="Confirmed orders" onOpen={showActivity}
              chip={`${sold}% sold`} chipTone={stats.confirmed_orders ? "good" : "neutral"} />
            <KpiCard icon="alert" tint={stats.oversold_units ? "red" : "green"} value={stats.oversold_units} label="Oversold units"
              onOpen={showActivity} danger={stats.oversold_units > 0}
              chip={`${stats.oversold_units} oversold`} chipTone={stats.oversold_units ? "bad" : "good"} />
            <KpiCard icon="activity" tint="pink" value={stats.rps} label="Requests per second" onOpen={showActivity}
              chip={`${stats.avg_latency_ms} ms avg`} chipTone={slow ? "bad" : "neutral"} />
          </section>

          <section className="charts">
            <div className="panel">
              <div className="panel-head"><h2>Requests per second</h2><span className="muted small">last 30 s</span></div>
              <RpsChart data={stats.series} />
            </div>
            <div className="panel">
              <div className="panel-head"><h2>Average latency</h2><span className="muted small">ms, last 60 s</span></div>
              <LatencyChart data={stats.series} />
            </div>
          </section>

          <section className="panel" ref={activityRef}>
            <div className="panel-head"><h2>Live activity</h2><span className="muted small">recent buyer events</span></div>
            <ActivityTable events={events ?? []} />
          </section>
        </>
      )}
    </>
  );
}
