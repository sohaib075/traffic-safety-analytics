"use client";

import { useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Bike, CalendarClock, Car, Clock3, Footprints, HardHat, MapPinned, ShieldAlert, TrendingUp, Users2 } from "lucide-react";
import { qs } from "@/lib/api";
import { CHART, CLASS_COLOR, EVENT_META, EVENT_TYPES, dayRange, fmtHour, nf } from "@/lib/format";
import { useApp, useFetch } from "@/lib/state";
import type { Bucket, Forecast, Summary, ZoneStat } from "@/lib/types";
import { Empty, Kpi, PageHeader, Panel, RiskLevel } from "@/components/ui";

const VEH = ["car", "motorcycle", "bus", "truck", "bicycle"];
const LEGEND = { iconType: "circle" as const, iconSize: 8, wrapperStyle: { fontSize: 12, paddingTop: 8, color: "#475569" } };

export default function AnalyticsPage() {
  const { day, live } = useApp();
  const [bucket, setBucket] = useState<"15min" | "hour">("hour");
  const range = dayRange(day);
  const { data: s } = useFetch<Summary>(`/api/stats/summary${qs(range)}`, [live.tick]);
  const { data: ts } = useFetch<{ buckets: Bucket[] }>(`/api/stats/timeseries${qs({ ...range, bucket })}`, [live.tick]);
  const { data: zones } = useFetch<ZoneStat[]>(`/api/stats/zones${qs(range)}`, [live.tick]);
  const { data: fc } = useFetch<Forecast>(`/api/stats/forecast`, [live.tick]);

  const rows = (ts?.buckets ?? []).map((b) => ({ ...b, label: fmtHour(b.start), ...b.by_type }));
  const moto = s?.volume.motorcycle ?? 0;
  const motoRatio = s && s.vehicles ? ((moto / s.vehicles) * 100).toFixed(1) : "—";
  const maxVol = s ? Math.max(1, ...Object.values(s.volume)) : 1;

  return (
    <div className="mx-auto max-w-[1500px] space-y-6">
      <PageHeader title="Analytics" subtitle="Traffic volume, safety events over time, zone performance and the traffic forecast." />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
        <Kpi label="Vehicles" value={s ? nf.format(s.vehicles) : "—"} icon={Car} tone="blue" />
        <Kpi label="Pedestrians" value={s ? nf.format(s.pedestrians) : "—"} icon={Footprints} tone="green" />
        <Kpi label="Motorcycle share" value={`${motoRatio}%`} icon={Bike} tone="cyan" />
        <Kpi
          label="Safety events"
          value={s?.total_events ?? "—"}
          icon={ShieldAlert}
          tone="orange"
          sub={s ? `${s.review_status.confirmed ?? 0} confirmed · ${s.review_status.dismissed ?? 0} dismissed` : undefined}
        />
        <Kpi
          label="Helmet compliance"
          icon={HardHat}
          tone="violet"
          value={s && s.helmet.checked ? `${Math.round((s.helmet.compliant / s.helmet.checked) * 100)}%` : "—"}
          sub={s ? (s.helmet.checked ? `${s.helmet.checked} judged · ${s.helmet.violations} potential violations` : "no helmet model configured") : undefined}
        />
        <Kpi label="Peak hour" value={s?.peak_hour ? fmtHour(s.peak_hour) : "—"} icon={Clock3} tone="slate" />
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Panel
          title="Traffic volume over time"
          icon={TrendingUp}
          right={
            <div className="flex rounded-lg border border-[var(--color-line)] bg-[var(--color-panel-2)] p-0.5 text-xs font-medium" role="group" aria-label="Time bucket">
              {(["hour", "15min"] as const).map((b) => (
                <button
                  key={b}
                  onClick={() => setBucket(b)}
                  aria-pressed={bucket === b}
                  className={`rounded-md px-2.5 py-1 ${bucket === b ? "bg-white text-[var(--color-ink)] shadow-sm" : "text-[var(--color-muted)] hover:text-[var(--color-ink)]"}`}
                >
                  {b === "hour" ? "Hourly" : "15 min"}
                </button>
              ))}
            </div>
          }
          bodyClass="px-3 pb-3 pt-4"
        >
          {rows.length ? (
            <ResponsiveContainer width="100%" height={280}>
              <AreaChart data={rows} margin={{ top: 4, right: 12, left: -12, bottom: 0 }}>
                <CartesianGrid stroke={CHART.grid} vertical={false} />
                <XAxis dataKey="label" tick={CHART.axis} axisLine={false} tickLine={false} />
                <YAxis tick={CHART.axis} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip {...CHART.tooltip} />
                <Legend {...LEGEND} />
                {VEH.map((k) => (
                  <Area isAnimationActive={false} key={k} type="monotone" dataKey={k} stackId="1" stroke={CLASS_COLOR[k]} fill={CLASS_COLOR[k]} fillOpacity={0.18} strokeWidth={2} />
                ))}
                <Area isAnimationActive={false} type="monotone" dataKey="pedestrian" stroke={CLASS_COLOR.pedestrian} fill="none" strokeWidth={2} strokeDasharray="5 4" />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <Empty>No traffic in range.</Empty>
          )}
        </Panel>

        <Panel title="Safety events over time" icon={ShieldAlert} bodyClass="px-3 pb-3 pt-4">
          {rows.some((r) => r.events) ? (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={rows} margin={{ top: 4, right: 12, left: -12, bottom: 0 }}>
                <CartesianGrid stroke={CHART.grid} vertical={false} />
                <XAxis dataKey="label" tick={CHART.axis} axisLine={false} tickLine={false} />
                <YAxis tick={CHART.axis} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip {...CHART.tooltip} />
                <Legend {...LEGEND} />
                {EVENT_TYPES.map((t) => (
                  <Bar isAnimationActive={false} key={t} dataKey={t} name={EVENT_META[t].short} stackId="e" fill={EVENT_META[t].color} maxBarSize={48} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <Empty>No events in range.</Empty>
          )}
        </Panel>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_1.2fr]">
        <Panel title="Volume by road-user type" icon={Users2}>
          {s && s.vehicles + s.pedestrians > 0 ? (
            <div className="space-y-3.5">
              {[...VEH, "pedestrian"].map((k) => {
                const v = s.volume[k] ?? 0;
                return (
                  <div key={k} className="grid grid-cols-[100px_1fr_64px] items-center gap-3 text-sm">
                    <span className="flex items-center gap-2 capitalize text-[var(--color-muted)]">
                      <span className="h-2.5 w-2.5 rounded-sm" style={{ background: CLASS_COLOR[k] }} /> {k}
                    </span>
                    <div className="h-2.5 rounded-full bg-[var(--color-panel-2)]">
                      <div className="h-2.5 rounded-full" style={{ width: `${(v / maxVol) * 100}%`, background: CLASS_COLOR[k] }} />
                    </div>
                    <span className="num text-right font-semibold">{nf.format(v)}</span>
                  </div>
                );
              })}
            </div>
          ) : (
            <Empty>No traffic in range.</Empty>
          )}
        </Panel>

        <Panel
          title="Traffic forecast"
          icon={CalendarClock}
          right={
            fc?.expected_congestion_window ? (
              <span className="rounded-full bg-amber-50 px-2.5 py-1 text-xs font-semibold text-amber-800 ring-1 ring-inset ring-amber-200">
                Expected peak {fc.expected_congestion_window.start}–{fc.expected_congestion_window.end}
              </span>
            ) : null
          }
          bodyClass="px-3 pb-3 pt-4"
        >
          {fc && fc.hours.some((h) => h.expected_vehicles != null) ? (
            <>
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={fc.hours.map((h) => ({ ...h, label: `${String(h.hour).padStart(2, "0")}:00` }))} margin={{ top: 4, right: 12, left: -12, bottom: 0 }}>
                  <CartesianGrid stroke={CHART.grid} vertical={false} />
                  <XAxis dataKey="label" tick={CHART.axis} axisLine={false} tickLine={false} interval={2} />
                  <YAxis tick={CHART.axis} axisLine={false} tickLine={false} />
                  <Tooltip {...CHART.tooltip} />
                  <Line isAnimationActive={false} type="monotone" dataKey="expected_vehicles" name="Expected vehicles / hour" stroke="#2563eb" strokeWidth={2.5} dot={{ r: 3, fill: "#2563eb" }} connectNulls={false} />
                </LineChart>
              </ResponsiveContainer>
              <p className="px-2 pb-1 pt-2 text-xs text-[var(--color-faint)]">
                {fc.method}; {fc.days_of_history} day(s) of history. Gaps are hours never observed.
              </p>
            </>
          ) : (
            <Empty>Not enough history to forecast.</Empty>
          )}
        </Panel>
      </div>

      <Panel title="Zones" icon={MapPinned} bodyClass="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-[var(--color-panel-2)] text-left text-xs font-semibold uppercase tracking-wide text-[var(--color-faint)]">
              <tr>
                <th className="px-5 py-3">Zone</th>
                <th className="px-3 py-3">Camera</th>
                <th className="px-3 py-3 text-right">Vehicles</th>
                <th className="px-3 py-3 text-right">Pedestrians</th>
                <th className="px-3 py-3 text-right">Avg occ.</th>
                <th className="px-3 py-3 text-right">Peak occ.</th>
                <th className="px-3 py-3 text-right">Avg speed</th>
                <th className="px-3 py-3 text-right">Events</th>
                <th className="px-5 py-3 text-right">Risk</th>
              </tr>
            </thead>
            <tbody className="num divide-y divide-[var(--color-line)]">
              {zones?.map((z) => (
                <tr key={`${z.camera_id}:${z.id}`} className="transition-colors hover:bg-[var(--color-panel-2)]">
                  <td className="px-5 py-3 font-medium">{z.name}</td>
                  <td className="px-3 py-3 text-[var(--color-muted)]">{z.camera_name}</td>
                  <td className="px-3 py-3 text-right">{z.vehicles}</td>
                  <td className="px-3 py-3 text-right">{z.pedestrians}</td>
                  <td className="px-3 py-3 text-right">{z.occupancy_avg ?? "—"}</td>
                  <td className="px-3 py-3 text-right">{z.occupancy_max ?? "—"}</td>
                  <td className="px-3 py-3 text-right">{z.speed_avg_mps != null ? `${z.speed_avg_mps} m/s` : "—"}</td>
                  <td className="px-3 py-3 text-right font-semibold">{z.events_total}</td>
                  <td className="px-5 py-3 text-right">
                    <span className="inline-flex items-center gap-2">
                      <RiskLevel risk={z.risk} /> <span className="text-xs text-[var(--color-faint)]">{z.risk.score}</span>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
