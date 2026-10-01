"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, ArrowRight, Car, Clapperboard, Footprints, Gauge, ShieldAlert, Siren, Video } from "lucide-react";
import { qs } from "@/lib/api";
import { CHART, CLASS_COLOR, LEVEL_COLOR, LEVEL_STYLE, dayRange, fmtDate, fmtHour, fmtTime, nf } from "@/lib/format";
import { useApp, useFetch } from "@/lib/state";
import type { Bucket, CameraInfo, Incident, Summary, ZoneStat } from "@/lib/types";
import { LiveFeed } from "@/components/LiveFeed";
import { ZoneMap } from "@/components/ZoneMap";
import { Empty, EventBadge, Kpi, Panel, RiskBreakdown, SeverityBadge } from "@/components/ui";

const VIOLATIONS = ["red_light", "wrong_way", "helmet_violation", "illegal_stop"];
const VEH = ["car", "motorcycle", "bus", "truck", "bicycle"];

export default function Dashboard() {
  const { day, live, can } = useApp();
  const range = dayRange(day);
  const q = qs(range);
  const { data: summary } = useFetch<Summary>(`/api/stats/summary${q}`, [live.tick]);
  const { data: zones } = useFetch<ZoneStat[]>(`/api/stats/zones${q}`, [live.tick]);
  const { data: ts } = useFetch<{ buckets: Bucket[] }>(`/api/stats/timeseries${qs({ ...range, bucket: "hour" })}`, [live.tick]);
  const { data: recent } = useFetch<{ items: Incident[]; total: number }>(`/api/incidents${qs({ ...range, limit: 7, status: "new,confirmed" })}`, [live.tick]);
  const { data: cameras } = useFetch<CameraInfo[]>("/api/cameras", [live.tick]);
  const [camId, setCamId] = useState<string | null>(null);

  const camera = useMemo(() => {
    if (!cameras?.length) return undefined;
    const liveCam = cameras.find((c) => live.progress[c.id]);
    const newest = [...cameras]
      .filter((c) => c.latest_job?.annotated_url)
      .sort((a, b) => (b.latest_job!.created_at > a.latest_job!.created_at ? 1 : -1))[0];
    return cameras.find((c) => c.id === camId) ?? liveCam ?? newest ?? cameras[0];
  }, [cameras, camId, live.progress]);

  const violations = summary ? VIOLATIONS.reduce((a, k) => a + (summary.events[k] ?? 0), 0) : null;
  const newIds = new Set(live.incidents.slice(0, 5).map((i) => i.id));
  const lvl = summary ? LEVEL_STYLE[summary.risk.level] : null;
  const dash = (v: number | null | undefined) => (v == null ? "—" : nf.format(v));

  return (
    <div className="mx-auto max-w-[1500px] space-y-6">
      {/* ------------------------------------------------------------ hero */}
      <section className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-[#0b1730] via-[#13235a] to-[#1d3fa8] px-6 py-6 text-white shadow-lg md:px-8">
        <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-blue-400/20 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-32 right-40 h-72 w-72 rounded-full bg-indigo-400/20 blur-3xl" />
        <div className="relative flex flex-wrap items-center gap-x-6 gap-y-4">
          <div className="min-w-[16rem] flex-[1_1_30rem]">
            <div className="text-xs font-semibold uppercase tracking-[0.12em] text-blue-200">
              {day ? fmtDate(`${day}T00:00:00`) : "All time"} · road safety overview
            </div>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight md:text-[28px]">
              {summary
                ? summary.total_events
                  ? `${nf.format(summary.total_events)} potential safety events across ${nf.format(summary.vehicles)} vehicles`
                  : `${nf.format(summary.vehicles)} vehicles observed — no safety events`
                : "Loading today's picture…"}
            </h1>
            <p className="mt-1.5 max-w-2xl text-sm text-blue-100/80">
              {summary?.top_zone ? `Highest observed risk concentration: ${summary.top_zone.name}. ` : ""}
              {summary?.peak_hour ? `Peak traffic around ${fmtHour(summary.peak_hour)}.` : ""}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {summary && lvl && (
              <div className="rounded-xl bg-white/10 px-4 py-3 ring-1 ring-white/15 backdrop-blur">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-blue-200">Risk indicator</div>
                <div className="mt-0.5 flex items-baseline gap-2">
                  <span className="text-2xl font-semibold" style={{ color: { LOW: "#86efac", MODERATE: "#fcd34d", HIGH: "#fca5a5", CRITICAL: "#fecaca" }[summary.risk.level] }}>
                    {summary.risk.level}
                  </span>
                  <span className="num text-xs text-blue-100/80">score {summary.risk.score}</span>
                </div>
              </div>
            )}
            {can("process") && (
              <Link href="/analyze" className="inline-flex items-center gap-2 rounded-xl bg-white px-4 py-3 text-sm font-semibold text-[#13235a] shadow-md transition hover:bg-blue-50">
                <Clapperboard className="h-4 w-4" /> Analyze a video
              </Link>
            )}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------ KPIs */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Vehicles" value={dash(summary?.vehicles)} sub={summary ? `${nf.format(summary.pedestrians)} pedestrians` : undefined} icon={Car} tone="blue" />
        <Kpi label="Violations" value={dash(violations)} sub="red-light · wrong-way · helmet · stopping" icon={ShieldAlert} tone="red" />
        <Kpi label="Near-misses" value={dash(summary ? summary.events.near_miss ?? 0 : null)} sub="potential, vehicle–vehicle" icon={Siren} tone="orange" />
        <Kpi label="Pedestrian conflicts" value={dash(summary ? summary.events.ped_conflict ?? 0 : null)} sub="potential, vehicle–pedestrian" icon={Footprints} tone="pink" />
      </div>

      {/* ------------------------------------------------------------ live + map */}
      <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
        <Panel
          title="Live traffic"
          icon={Video}
          right={
            cameras && cameras.length > 1 ? (
              <select className="input py-1.5 text-xs" value={camera?.id} onChange={(e) => setCamId(e.target.value)} aria-label="Camera">
                {cameras.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            ) : null
          }
          bodyClass="p-4"
        >
          <LiveFeed camera={camera} />
          {camera && live.progress[camera.id] && (
            <div className="mt-3 flex flex-wrap gap-2 text-xs">
              {Object.entries(live.progress[camera.id].live.objects).map(([k, v]) => (
                <span key={k} className="inline-flex items-center gap-1.5 rounded-full bg-[var(--color-panel-2)] px-2.5 py-1 font-medium">
                  <span className="h-2 w-2 rounded-full" style={{ background: CLASS_COLOR[k] ?? "#94a3b8" }} /> {k} {v}
                </span>
              ))}
              {Object.entries(live.progress[camera.id].live.signals).map(([k, v]) => (
                <span key={k} className={`rounded-full px-2.5 py-1 font-medium ${v === "red" ? "bg-red-50 text-red-700" : "bg-emerald-50 text-emerald-700"}`}>
                  signal {k}: {v}
                </span>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Road risk map" icon={Activity} right={<Link href="/map" className="inline-flex items-center gap-1 text-xs font-semibold text-[var(--color-accent)] hover:underline">Open map <ArrowRight className="h-3.5 w-3.5" /></Link>} bodyClass="p-4">
          <div className="overflow-hidden rounded-xl ring-1 ring-[var(--color-line)]">
            {zones ? <ZoneMap zones={zones} height={330} /> : <div className="h-[330px] animate-pulse bg-[var(--color-panel-2)]" />}
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-[var(--color-muted)]">
            {Object.entries(LEVEL_COLOR).map(([k, c]) => (
              <span key={k} className="inline-flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: c }} /> {k.charAt(0) + k.slice(1).toLowerCase()}
              </span>
            ))}
            <span className="ml-auto text-[var(--color-faint)]">observed event density</span>
          </div>
        </Panel>
      </div>

      {/* ------------------------------------------------------------ incidents + breakdown */}
      <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
        <Panel
          title="Recent incidents"
          icon={ShieldAlert}
          right={<Link href="/incidents" className="inline-flex items-center gap-1 text-xs font-semibold text-[var(--color-accent)] hover:underline">View all{recent ? ` ${recent.total}` : ""} <ArrowRight className="h-3.5 w-3.5" /></Link>}
          bodyClass="p-0"
        >
          {recent && recent.items.length === 0 && <Empty>No incidents in this range.</Empty>}
          <ul className="divide-y divide-[var(--color-line)]">
            {recent?.items.map((i) => (
              <li key={i.id}>
                <Link
                  href={`/incidents?id=${i.id}`}
                  className={`grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1 px-5 py-3 transition-colors hover:bg-[var(--color-panel-2)] sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_auto_auto] ${newIds.has(i.id) ? "flash" : ""}`}
                >
                  <EventBadge t={i.type} />
                  <span className="hidden truncate text-sm text-[var(--color-muted)] sm:block">{i.zone_name ?? i.camera_id}</span>
                  <span className="hidden sm:block"><SeverityBadge s={i.severity} /></span>
                  <span className="num text-right text-sm font-medium text-[var(--color-muted)]">{fmtTime(i.occurred_at, false)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </Panel>

        <div className="grid gap-6">
          <Panel title="What drives the risk score" icon={Gauge}>
            {summary ? <RiskBreakdown risk={summary.risk} /> : <div className="h-24 animate-pulse rounded-lg bg-[var(--color-panel-2)]" />}
            {summary && <p className="mt-4 text-xs leading-relaxed text-[var(--color-faint)]">{summary.risk.method}</p>}
          </Panel>
          <Panel title="Traffic by hour" icon={Car} bodyClass="px-3 pb-3 pt-4">
            {ts && ts.buckets.length > 0 ? (
              <>
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={ts.buckets.map((b) => ({ ...b, hour: fmtHour(b.start) }))} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
                    <CartesianGrid stroke={CHART.grid} vertical={false} />
                    <XAxis dataKey="hour" tick={CHART.axis} axisLine={false} tickLine={false} />
                    <YAxis tick={CHART.axis} axisLine={false} tickLine={false} allowDecimals={false} />
                    <Tooltip {...CHART.tooltip} />
                    {VEH.map((k, i) => (
                      <Bar isAnimationActive={false} key={k} dataKey={k} stackId="v" fill={CLASS_COLOR[k]} radius={i === VEH.length - 1 ? [4, 4, 0, 0] : 0} />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
                <div className="mt-2 flex flex-wrap justify-center gap-3 text-xs text-[var(--color-muted)]">
                  {VEH.map((k) => (
                    <span key={k} className="inline-flex items-center gap-1.5 capitalize">
                      <span className="h-2.5 w-2.5 rounded-sm" style={{ background: CLASS_COLOR[k] }} /> {k}
                    </span>
                  ))}
                </div>
              </>
            ) : (
              <Empty>No traffic in range.</Empty>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
