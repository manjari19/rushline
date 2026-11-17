import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmt, SeriesPoint } from "../api";

const PURPLE = "#7C5CFC";
const clock = (t: number) => new Date(t * 1000).toLocaleTimeString([], { minute: "2-digit", second: "2-digit" });
const axisTick = { fill: "#9A96A8", fontSize: 11 };

function DarkTooltip({ active, payload, label, unit }: { active?: boolean; payload?: { value: number }[]; label?: number; unit: string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tooltip-dark">
      <div className="tooltip-time">{clock(Number(label))}</div>
      <b>{fmt(payload[0].value)}</b> {unit}
    </div>
  );
}

/** Floating value bubble above the most recent bar only. */
function LastBarBubble({ x, y, width, value, index, count }: { x?: number; y?: number; width?: number; value?: number; index?: number; count: number }) {
  if (index !== count - 1 || x === undefined || y === undefined || width === undefined) return null;
  const text = fmt(value ?? 0);
  const w = Math.max(32, text.length * 8 + 16);
  const cx = x + width / 2;
  return (
    <g>
      <rect x={cx - w / 2} y={y - 32} width={w} height={22} rx={6} fill="#1B1530" />
      <path d={`M${cx - 5} ${y - 10} L${cx} ${y - 4} L${cx + 5} ${y - 10} Z`} fill="#1B1530" />
      <text x={cx} y={y - 17} textAnchor="middle" fill="#fff" fontSize={12} fontWeight={700}>{text}</text>
    </g>
  );
}

export function RpsChart({ data }: { data: SeriesPoint[] }) {
  const bars = data.slice(-30);
  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={bars} margin={{ top: 36, right: 24, left: -8, bottom: 0 }} barCategoryGap="22%">
          <defs>
            <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="6" height="6" fill="#F1ECFF" />
              <line x1="0" y1="0" x2="0" y2="6" stroke="#D5C9FF" strokeWidth="2.2" />
            </pattern>
          </defs>
          <CartesianGrid stroke="#EEECF4" vertical={false} />
          <XAxis dataKey="t" tickFormatter={clock} tick={axisTick} tickLine={false} axisLine={false} minTickGap={36} />
          <YAxis tick={axisTick} tickLine={false} axisLine={false} width={44} allowDecimals={false} tickFormatter={fmt} />
          <Tooltip cursor={{ fill: "rgba(124,92,252,0.06)" }} content={<DarkTooltip unit="req/s" />} />
          <Bar dataKey="rps" radius={[4, 4, 0, 0]} isAnimationActive={false}
            label={(p: object) => <LastBarBubble {...(p as Record<string, number>)} count={bars.length} />}>
            {bars.map((_, i) => (
              <Cell key={i} fill={i === bars.length - 1 ? PURPLE : "url(#hatch)"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function LatencyChart({ data }: { data: SeriesPoint[] }) {
  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 12, right: 24, left: -8, bottom: 0 }}>
          <defs>
            <linearGradient id="latFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={PURPLE} stopOpacity={0.28} />
              <stop offset="100%" stopColor={PURPLE} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#EEECF4" vertical={false} />
          <XAxis dataKey="t" tickFormatter={clock} tick={axisTick} tickLine={false} axisLine={false} minTickGap={36} />
          <YAxis tick={axisTick} tickLine={false} axisLine={false} width={44} />
          <Tooltip content={<DarkTooltip unit="ms" />} />
          <Area type="monotone" dataKey="avg_ms" stroke={PURPLE} strokeWidth={2} fill="url(#latFill)" isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
