import { fmt } from "../api";
import Icon, { IconName } from "./Icon";

export type Tone = "good" | "bad" | "neutral";

interface Props {
  icon: IconName;
  tint: "purple" | "amber" | "teal" | "green" | "pink" | "red";
  value: number;
  label: string;
  chip: string;
  chipTone: Tone;
  danger?: boolean;
  onOpen?: () => void;
}

export default function KpiCard({ icon, tint, value, label, chip, chipTone, danger, onOpen }: Props) {
  return (
    <div className={`kpi ${danger ? "kpi-danger" : ""}`}>
      <div className="kpi-top">
        <span className={`icon-chip tint-${tint}`}><Icon name={icon} /></span>
        <button className="kpi-open" onClick={onOpen} aria-label={`Show recent activity for ${label}`}>
          <Icon name="arrow" size={14} />
        </button>
      </div>
      <div className="kpi-value">{fmt(value)}</div>
      <div className="kpi-label">{label}</div>
      <span className={`chip chip-${chipTone}`}>{chip}</span>
    </div>
  );
}
