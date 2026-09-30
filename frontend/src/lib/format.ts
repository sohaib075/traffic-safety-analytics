export const EVENT_META: Record<string, { label: string; short: string; color: string }> = {
  near_miss: { label: "Potential Near-Miss", short: "Near-Miss", color: "#f97316" },
  ped_conflict: { label: "Potential Pedestrian Conflict", short: "Ped Conflict", color: "#ec4899" },
  red_light: { label: "Red-Light Event", short: "Red-Light", color: "#ef4444" },
  wrong_way: { label: "Potential Wrong-Way", short: "Wrong-Way", color: "#a855f7" },
  illegal_stop: { label: "Potential Illegal Stopping", short: "Illegal Stop", color: "#64748b" },
  congestion: { label: "Congestion", short: "Congestion", color: "#eab308" },
  helmet_violation: { label: "Potential Helmet Violation", short: "Helmet", color: "#06b6d4" },
};

export const EVENT_TYPES = Object.keys(EVENT_META);

export function eventLabel(t: string, short = false) {
  const m = EVENT_META[t];
  return m ? (short ? m.short : m.label) : t;
}

export const SEVERITY_COLOR: Record<string, string> = {
  high: "#ef4444",
  medium: "#f59e0b",
  low: "#84cc16",
};

export const LEVEL_COLOR: Record<string, string> = {
  LOW: "#22c55e",
  MODERATE: "#eab308",
  HIGH: "#ef4444",
  CRITICAL: "#b91c1c",
};

export const CLASS_COLOR: Record<string, string> = {
  car: "#3b82f6",
  motorcycle: "#06b6d4",
  bus: "#a855f7",
  truck: "#f97316",
  bicycle: "#84cc16",
  pedestrian: "#22c55e",
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
