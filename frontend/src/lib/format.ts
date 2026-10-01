// color = marks/bars (≥3:1 on white); text/bg = readable label on a soft tint (≥4.5:1).
export const EVENT_META: Record<string, { label: string; short: string; color: string; text: string; bg: string }> = {
  near_miss: { label: "Potential Near-Miss", short: "Near-Miss", color: "#ea580c", text: "#9a3412", bg: "#fff1e6" },
  ped_conflict: { label: "Potential Pedestrian Conflict", short: "Ped Conflict", color: "#db2777", text: "#9d174d", bg: "#fdf0f6" },
  red_light: { label: "Red-Light Event", short: "Red-Light", color: "#dc2626", text: "#991b1b", bg: "#fef0f0" },
  wrong_way: { label: "Potential Wrong-Way", short: "Wrong-Way", color: "#7c3aed", text: "#5b21b6", bg: "#f4f0ff" },
  illegal_stop: { label: "Potential Illegal Stopping", short: "Illegal Stop", color: "#475569", text: "#334155", bg: "#f1f4f8" },
  congestion: { label: "Congestion", short: "Congestion", color: "#ca8a04", text: "#854d0e", bg: "#fdf8e6" },
  helmet_violation: { label: "Potential Helmet Violation", short: "Helmet", color: "#0891b2", text: "#155e75", bg: "#ecfafd" },
};

export const EVENT_TYPES = Object.keys(EVENT_META);

export function eventLabel(t: string, short = false) {
  const m = EVENT_META[t];
  return m ? (short ? m.short : m.label) : t;
}

export const SEVERITY_COLOR: Record<string, string> = {
  high: "#dc2626",
  medium: "#d97706",
  low: "#65a30d",
};
export const SEVERITY_STYLE: Record<string, { text: string; bg: string; ring: string }> = {
  high: { text: "#991b1b", bg: "#fef2f2", ring: "#fecaca" },
  medium: { text: "#92400e", bg: "#fffbeb", ring: "#fde68a" },
  low: { text: "#3f6212", bg: "#f7fee7", ring: "#d9f99d" },
};

export const LEVEL_COLOR: Record<string, string> = {
  LOW: "#16a34a",
  MODERATE: "#d97706",
  HIGH: "#dc2626",
  CRITICAL: "#991b1b",
};
export const LEVEL_STYLE: Record<string, { text: string; bg: string }> = {
  LOW: { text: "#166534", bg: "#f0fdf4" },
  MODERATE: { text: "#92400e", bg: "#fffbeb" },
  HIGH: { text: "#991b1b", bg: "#fef2f2" },
  CRITICAL: { text: "#7f1d1d", bg: "#fee2e2" },
};

export const CLASS_COLOR: Record<string, string> = {
  car: "#2563eb",
  motorcycle: "#0891b2",
  bus: "#7c3aed",
  truck: "#ea580c",
  bicycle: "#65a30d",
  pedestrian: "#16a34a",
  rider: "#0e7490",
};

/** Shared chart styling (Recharts) for the light theme. */
export const CHART = {
  grid: "#e2e8f0",
  axis: { fill: "#64748b", fontSize: 11 },
  tooltip: {
    contentStyle: { background: "#ffffff", border: "1px solid #e2e8f0", borderRadius: 10, fontSize: 12, boxShadow: "0 10px 30px -8px rgb(15 23 42 / .2)" },
    labelStyle: { color: "#0f172a", fontWeight: 600 },
    cursor: { fill: "#0f172a0a" },
  },
};

export const nf = new Intl.NumberFormat("en-US");

export function fmtTime(iso: string, withSeconds = true) {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", ...(withSeconds ? { second: "2-digit" } : {}) });
}

export function fmtDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}

export function fmtHour(iso: string) {
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

/** Local-time ISO without timezone, matching the backend's naive datetimes. */
export function localIso(d: Date) {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

export function dayRange(day: string | null): { start?: string; end?: string } {
  if (!day) return {};
  const s = new Date(`${day}T00:00:00`);
  const e = new Date(s);
  e.setDate(e.getDate() + 1);
  return { start: localIso(s), end: localIso(e) };
}
