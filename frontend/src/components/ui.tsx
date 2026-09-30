"use client";

import { EVENT_META, LEVEL_COLOR, SEVERITY_COLOR, eventLabel } from "@/lib/format";
import type { Risk } from "@/lib/types";

export function Panel({
  title,
  right,
  children,
  className = "",
  bodyClass = "p-4",
}: {
  title?: React.ReactNode;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClass?: string;
}) {
  return (
    <section className={`panel flex min-w-0 flex-col ${className}`}>
      {(title || right) && (
        <header className="flex items-center gap-2 border-b border-[var(--color-line)] px-4 py-2.5">
          <h2 className="panel-title">{title}</h2>
          <div className="ml-auto flex items-center gap-2">{right}</div>
        </header>
      )}
      <div className={`min-h-0 flex-1 ${bodyClass}`}>{children}</div>
    </section>
  );
}

export function Kpi({ label, value, sub, color }: { label: string; value: React.ReactNode; sub?: React.ReactNode; color?: string }) {
  return (
    <div className="panel px-4 py-3">
      <div className="panel-title">{label}</div>
      <div className="num mt-1 text-2xl font-semibold" style={color ? { color } : undefined}>
        {value}
      </div>
      {sub && <div className="mt-0.5 text-xs text-[var(--color-muted)]">{sub}</div>}
    </div>
  );
}

export function SeverityBadge({ s }: { s: string }) {
  const c = SEVERITY_COLOR[s] ?? "#8b98ab";
  return (
    <span
      className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
      style={{ color: c, background: `${c}1f` }}
    >
      {s}
    </span>
  );
}

export function EventBadge({ t, short = true }: { t: string; short?: boolean }) {
  const c = EVENT_META[t]?.color ?? "#8b98ab";
  return (
    <span className="inline-flex items-center gap-1.5 text-sm">
      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: c }} />
      {eventLabel(t, short)}
    </span>
  );
}

export function StatusBadge({ s }: { s: string }) {
  const map: Record<string, string> = {
    new: "text-sky-300 bg-sky-500/10",
    confirmed: "text-red-300 bg-red-500/10",
    dismissed: "text-[var(--color-faint)] bg-white/5",
    running: "text-amber-300 bg-amber-500/10",
    done: "text-emerald-300 bg-emerald-500/10",
    failed: "text-red-300 bg-red-500/10",
    queued: "text-[var(--color-muted)] bg-white/5",
    cancelled: "text-[var(--color-faint)] bg-white/5",
  };
  return <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${map[s] ?? ""}`}>{s}</span>;
}

export function RiskLevel({ risk, big = false }: { risk: Risk; big?: boolean }) {
  const c = LEVEL_COLOR[risk.level];
  return (
    <span className={`font-semibold tracking-wide ${big ? "text-3xl" : "text-sm"}`} style={{ color: c }}>
      {risk.level}
    </span>
  );
}

export function RiskBreakdown({ risk }: { risk: Risk }) {
  const max = Math.max(1, ...risk.breakdown.map((b) => b.points));
  return (
    <div className="space-y-2">
      {risk.breakdown.length === 0 && <p className="text-sm text-[var(--color-muted)]">No events in range.</p>}
      {risk.breakdown.map((b) => (
        <div key={b.type} className="text-xs">
          <div className="mb-1 flex justify-between">
            <span>{eventLabel(b.type, true)}</span>
            <span className="num text-[var(--color-muted)]">
              {b.count} × w{b.weight} → <span className="text-[var(--color-ink)]">{b.points}</span> pts
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-[var(--color-panel-2)]">
            <div
              className="h-1.5 rounded-full"
              style={{ width: `${(b.points / max) * 100}%`, background: EVENT_META[b.type]?.color ?? "#8b98ab" }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="grid place-items-center py-10 text-center text-sm text-[var(--color-muted)]">{children}</div>;
}

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return <div className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</div>;
}
