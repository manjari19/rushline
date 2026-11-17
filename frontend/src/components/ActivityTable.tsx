import { useState } from "react";
import { ActivityEvent, EventType, fmt } from "../api";

const LABEL: Record<EventType, { text: string; tone: string }> = {
  confirmed: { text: "Confirmed", tone: "green" },
  reserved: { text: "Reserved", tone: "purple" },
  waiting: { text: "Waiting", tone: "amber" },
  expired: { text: "Expired", tone: "gray" },
  rejected: { text: "Sold out", tone: "red" },
};

const time = (ts: number) => new Date(ts * 1000).toLocaleTimeString([], { hour12: false });

const FILTERS: { key: "all" | EventType; label: string }[] = [
  { key: "all", label: "All" },
  { key: "confirmed", label: "Confirmed" },
  { key: "reserved", label: "Reserved" },
  { key: "expired", label: "Expired" },
  { key: "rejected", label: "Sold out" },
];
const ROWS = 12;

export default function ActivityTable({ events }: { events: ActivityEvent[] }) {
  const [filter, setFilter] = useState<"all" | EventType>("all");
  const rows = events.filter((e) => filter === "all" || e.event === filter).slice(0, ROWS);

  return (
    <>
      <div className="filter-tabs" role="tablist" aria-label="Filter activity">
        {FILTERS.map((f) => (
          <button key={f.key} role="tab" aria-selected={filter === f.key} className={filter === f.key ? "active" : ""}
            onClick={() => setFilter(f.key)}>{f.label}</button>
        ))}
      </div>
      <Table rows={rows} filtered={filter !== "all"} />
    </>
  );
}

function Table({ rows, filtered }: { rows: ActivityEvent[]; filtered: boolean }) {
  return (
    <table className="activity">
      <thead>
        <tr><th>Buyer</th><th>Event</th><th className="num">Units</th><th className="num">Time</th></tr>
      </thead>
      <tbody>
        {rows.length === 0 && (
          <tr><td colSpan={4} className="empty-row">
            {filtered ? "Nothing here yet." : "No activity yet. Start a rush or open the buyer view."}
          </td></tr>
        )}
        {rows.map((e, i) => (
          <tr key={`${e.ts}-${e.buyer_id}-${i}`}>
            <td className="buyer-cell" title={e.buyer_id}>
              {e.event === "rejected" && e.units > 1 ? `${fmt(e.units)} buyers` : e.buyer_id}
            </td>
            <td><span className={`pill pill-${LABEL[e.event].tone}`}>{LABEL[e.event].text}</span></td>
            <td className="num">{fmt(e.units)}</td>
            <td className="num muted">{time(e.ts)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
