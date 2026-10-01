"use client";

import { AlertTriangle, Inbox } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { EVENT_META, LEVEL_COLOR, LEVEL_STYLE, SEVERITY_STYLE, eventLabel } from "@/lib/format";
import type { Risk } from "@/lib/types";

export function Panel({
  title,
  icon: Icon,
  right,
  children,
  className = "",
  bodyClass = "p-5",
}: {
  title?: React.ReactNode;
  icon?: LucideIcon;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClass?: string;
}) {
  return (
    <section className={`panel flex min-w-0 flex-col ${className}`}>
      {(title || right) && (
        <header className="flex items-center gap-2 border-b border-[var(--color-line)] px-5 py-3.5">
          {Icon && <Icon className="h-4 w-4 text-[var(--color-faint)]" />}
          <h2 className="panel-title">{title}</h2>
          <div className="ml-auto flex items-center gap-2">{right}</div>
        </header>
      )}
      <div className={`min-h-0 flex-1 ${bodyClass}`}>{children}</div>
    </section>
  );
}

/** Page heading used at the top of each screen. */
export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end gap-3">
      <div className="min-w-0 flex-1">
        <h1 className="text-[22px] font-semibold tracking-tight text-[var(--color-ink)]">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-[var(--color-muted)]">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

const TONES = {
  blue: { fg: "#1d4ed8", bg: "#eff4ff" },
  orange: { fg: "#c2410c", bg: "#fff3eb" },
  pink: { fg: "#be185d", bg: "#fdf0f6" },
  violet: { fg: "#6d28d9", bg: "#f4f0ff" },
  green: { fg: "#15803d", bg: "#effbf3" },
  cyan: { fg: "#0e7490", bg: "#ecfafd" },
  slate: { fg: "#334155", bg: "#f1f4f8" },
  red: { fg: "#b91c1c", bg: "#fef2f2" },
} as const;
export type Tone = keyof typeof TONES;

export function Kpi({
  label,
  value,
  sub,
  icon: Icon,
  tone = "blue",
  valueColor,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  icon?: LucideIcon;
  tone?: Tone;
  valueColor?: string;
}) {
  const t = TONES[tone];
  return (
    <div className="panel flex items-start gap-3.5 px-5 py-4">
      {Icon && (
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl" style={{ background: t.bg, color: t.fg }}>
          <Icon className="h-5 w-5" />
        </span>
      )}
      <div className="min-w-0">
        <div className="text-[13px] font-medium text-[var(--color-muted)]">{label}</div>
        <div className="num mt-0.5 text-[26px] font-semibold leading-tight tracking-tight" style={valueColor ? { color: valueColor } : undefined}>
          {value}
        </div>
        {sub && <div className="mt-0.5 truncate text-xs text-[var(--color-faint)]">{sub}</div>}
      </div>
    </div>
  );
}

export function SeverityBadge({ s }: { s: string }) {
  const st = SEVERITY_STYLE[s] ?? { text: "#334155", bg: "#f1f5f9", ring: "#e2e8f0" };
  return (
    <span
      className="inline-flex items-center rounded-md px-2 py-0.5 text-[11px] font-semibold capitalize"
      style={{ color: st.text, background: st.bg, boxShadow: `inset 0 0 0 1px ${st.ring}` }}
    >
      {s}
    </span>
  );
}

export function EventBadge({ t, short = true, pill = false }: { t: string; short?: boolean; pill?: boolean }) {
  const m = EVENT_META[t];
  if (pill && m) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium" style={{ color: m.text, background: m.bg }}>
        <span className="h-1.5 w-1.5 rounded-full" style={{ background: m.color }} />
        {eventLabel(t, short)}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-2 text-sm font-medium text-[var(--color-ink)]">
      <span className="h-2.5 w-2.5 shrink-0 rounded-full ring-2 ring-white" style={{ background: m?.color ?? "#94a3b8" }} />
      {eventLabel(t, short)}
    </span>
  );
}

const STATUS: Record<string, string> = {
  new: "text-blue-700 bg-blue-50 ring-blue-200",
  confirmed: "text-red-700 bg-red-50 ring-red-200",
  dismissed: "text-slate-600 bg-slate-100 ring-slate-200",
  running: "text-amber-800 bg-amber-50 ring-amber-200",
  done: "text-emerald-700 bg-emerald-50 ring-emerald-200",
  failed: "text-red-700 bg-red-50 ring-red-200",
  queued: "text-slate-600 bg-slate-100 ring-slate-200",
  cancelled: "text-slate-600 bg-slate-100 ring-slate-200",
};

export function StatusBadge({ s }: { s: string }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-semibold capitalize ring-1 ring-inset ${STATUS[s] ?? STATUS.queued}`}>
      {s === "running" && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500" />}
      {s}
    </span>
  );
}

export function RiskLevel({ risk, big = false }: { risk: Risk; big?: boolean }) {
  const st = LEVEL_STYLE[risk.level];
  if (big) {
    return (
      <span className="text-[26px] font-semibold leading-tight tracking-tight" style={{ color: st.text }}>
        {risk.level}
      </span>
    );
  }
  return (
    <span className="rounded-md px-2 py-0.5 text-[11px] font-semibold" style={{ color: st.text, background: st.bg }}>
      {risk.level}
    </span>
  );
}

export function RiskBreakdown({ risk }: { risk: Risk }) {
  const max = Math.max(1, ...risk.breakdown.map((b) => b.points));
  return (
    <div className="space-y-3">
      {risk.breakdown.length === 0 && <p className="text-sm text-[var(--color-muted)]">No events in range.</p>}
      {risk.breakdown.map((b) => (
        <div key={b.type} className="text-[13px]">
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <EventBadge t={b.type} />
            <span className="num text-xs text-[var(--color-faint)]">
              {b.count} × w{b.weight} = <span className="font-semibold text-[var(--color-ink)]">{b.points}</span> pts
            </span>
          </div>
          <div className="h-2 rounded-full bg-[var(--color-panel-2)]">
            <div className="h-2 rounded-full" style={{ width: `${(b.points / max) * 100}%`, background: EVENT_META[b.type]?.color ?? "#94a3b8" }} />
          </div>
        </div>
      ))}
    </div>
  );
}

export function LevelDot({ level }: { level: string }) {
  return <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: LEVEL_COLOR[level] }} />;
}

export function Empty({ children, icon: Icon = Inbox }: { children: React.ReactNode; icon?: LucideIcon }) {
  return (
    <div className="grid place-items-center gap-2 py-10 text-center text-sm text-[var(--color-muted)]">
      <span className="grid h-10 w-10 place-items-center rounded-full bg-[var(--color-panel-2)] text-[var(--color-faint)]">
        <Icon className="h-5 w-5" />
      </span>
      <div className="max-w-sm">{children}</div>
    </div>
  );
}

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <div role="alert" className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-800">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "ok"; children: React.ReactNode }) {
  const cls = {
    info: "border-blue-200 bg-blue-50 text-blue-900",
    warn: "border-amber-200 bg-amber-50 text-amber-900",
    ok: "border-emerald-200 bg-emerald-50 text-emerald-900",
  }[tone];
  return <div className={`rounded-lg border px-3.5 py-2.5 text-sm ${cls}`}>{children}</div>;
}
