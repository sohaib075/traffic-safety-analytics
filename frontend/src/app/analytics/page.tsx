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
import { qs } from "@/lib/api";
import { CLASS_COLOR, EVENT_META, EVENT_TYPES, dayRange, fmtHour, nf } from "@/lib/format";
import { useApp, useFetch } from "@/lib/state";
import type { Bucket, Forecast, Summary, ZoneStat } from "@/lib/types";
import { Empty, Kpi, Panel } from "@/components/ui";

const AX = { fill: "#8b98ab", fontSize: 11 };
const TT = { contentStyle: { background: "#151d2b", border: "1px solid #1f2a3a", borderRadius: 8, fontSize: 12 }, cursor: { fill: "#ffffff08" } };
const VEH = ["car", "motorcycle", "bus", "truck", "bicycle"];

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

  return (
    <div className="mx-auto max-w-[1500px] space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Kpi label="Vehicles" value={s ? nf.format(s.vehicles) : "—"} />
        <Kpi label="Pedestrians" value={s ? nf.format(s.pedestrians) : "—"} />
        <Kpi label="Motorcycle ratio" value={`${motoRatio}%`} />
        <Kpi label="Events" value={s?.total_events ?? "—"} sub={s ? `${s.review_status.confirmed ?? 0} confirmed · ${s.review_status.dismissed ?? 0} dismissed` : undefined} />
        <Kpi
          label="Helmet compliance"
          value={s && s.helmet.checked ? `${Math.round((s.helmet.compliant / s.helmet.checked) * 100)}%` : "—"}
          sub={s ? (s.helmet.checked ? `${s.helmet.checked} checked · ${s.helmet.violations} potential violations` : "no helmet model configured") : undefined}
        />
        <Kpi label="Peak hour" value={s?.peak_hour ? fmtHour(s.peak_hour) : "—"} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel
          title="Traffic volume over time"
          right={
            <select className="input py-0.5 text-xs" value={bucket} onChange={(e) => setBucket(e.target.value as any)}>
              <option value="hour">Hourly</option>
              <option value="15min">15 min</option>
            </select>
          }
          bodyClass="p-2"
        >
          {rows.length ? (
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart data={rows} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
                <CartesianGrid stroke="#1f2a3a" vertical={false} />
                <XAxis dataKey="label" tick={AX} axisLine={false} tickLine={false} />
                <YAxis tick={AX} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip {...TT} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                {VEH.map((k) => (
                  <Area isAnimationActive={false} key={k} type="monotone" dataKey={k} stackId="1" stroke={CLASS_COLOR[k]} fill={CLASS_COLOR[k]} fillOpacity={0.35} />
                ))}
                <Area isAnimationActive={false} type="monotone" dataKey="pedestrian" stroke={CLASS_COLOR.pedestrian} fill="none" strokeDasharray="4 3" />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <Empty>No traffic in range.</Empty>
          )}
        </Panel>

        <Panel title="Safety events over time" bodyClass="p-2">
          {rows.some((r) => r.events) ? (
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={rows} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
                <CartesianGrid stroke="#1f2a3a" vertical={false} />
                <XAxis dataKey="label" tick={AX} axisLine={false} tickLine={false} />
                <YAxis tick={AX} axisLine={false} tickLine={false} allowDecimals={false} />
                <Tooltip {...TT} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                {EVENT_TYPES.map((t) => (
                  <Bar isAnimationActive={false} key={t} dataKey={t} name={EVENT_META[t].short} stackId="e" fill={EVENT_META[t].color} />
                ))}
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <Empty>No events in range.</Empty>
          )}
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_1.2fr]">
        <Panel title="Volume by class" bodyClass="p-4">
          {s && s.vehicles + s.pedestrians > 0 ? (
            <div className="space-y-2.5">
              {[...VEH, "pedestrian"].map((k) => {
                const v = s.volume[k] ?? 0;
                const max = Math.max(1, ...Object.values(s.volume));
                return (
                  <div key={k} className="grid grid-cols-[90px_1fr_60px] items-center gap-3 text-sm">
                    <span className="capitalize text-[var(--color-muted)]">{k}</span>
                    <div className="h-2 rounded-full bg-[var(--color-panel-2)]">
                      <div className="h-2 rounded-full" style={{ width: `${(v / max) * 100}%`, background: CLASS_COLOR[k] }} />
                    </div>
                    <span className="num text-right">{nf.format(v)}</span>
                  </div>
                );
              })}
            </div>
          ) : (
            <Empty>No traffic in range.</Empty>
          )}
        </Panel>

        <Panel
          title="Traffic forecast (statistical baseline)"
          right={
            fc?.expected_congestion_window ? (
              <span className="text-xs text-amber-300">
                Expected peak window {fc.expected_congestion_window.start}–{fc.expected_congestion_window.end}
              </span>
            ) : null
          }
          bodyClass="p-2"
        >
          {fc && fc.hours.some((h) => h.expected_vehicles != null) ? (
            <>
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={fc.hours.map((h) => ({ ...h, label: `${String(h.hour).padStart(2, "0")}:00` }))} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
                  <CartesianGrid stroke="#1f2a3a" vertical={false} />
                  <XAxis dataKey="label" tick={AX} axisLine={false} tickLine={false} interval={2} />
                  <YAxis tick={AX} axisLine={false} tickLine={false} />
                  <Tooltip {...TT} />
                  <Line isAnimationActive={false} type="monotone" dataKey="expected_vehicles" name="Expected vehicles / hour" stroke="#3b82f6" strokeWidth={2} dot={{ r: 2 }} connectNulls={false} />
                </LineChart>
              </ResponsiveContainer>
              <p className="px-2 pb-1 text-[11px] text-[var(--color-faint)]">
                {fc.method}; {fc.days_of_history} day(s) of history. Gaps are hours never observed.
              </p>
            </>
          ) : (
            <Empty>Not enough history to forecast.</Empty>
          )}
        </Panel>
      </div>

      <Panel title="Zones" bodyClass="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-[var(--color-muted)]">
              <tr className="border-b border-[var(--color-line)]">
                <th className="px-4 py-2 font-medium">Zone</th>
                <th className="px-2 py-2 font-medium">Camera</th>
                <th className="px-2 py-2 text-right font-medium">Vehicles</th>
                <th className="px-2 py-2 text-right font-medium">Pedestrians</th>
                <th className="px-2 py-2 text-right font-medium">Avg occ.</th>
                <th className="px-2 py-2 text-right font-medium">Peak occ.</th>
                <th className="px-2 py-2 text-right font-medium">Avg speed</th>
                <th className="px-2 py-2 text-right font-medium">Events</th>
                <th className="px-4 py-2 text-right font-medium">Risk</th>
              </tr>
            </thead>
            <tbody className="num divide-y divide-[var(--color-line)]">
              {zones?.map((z) => (
                <tr key={`${z.camera_id}:${z.id}`}>
                  <td className="px-4 py-2">{z.name}</td>
                  <td className="px-2 py-2 text-[var(--color-muted)]">{z.camera_name}</td>
                  <td className="px-2 py-2 text-right">{z.vehicles}</td>
                  <td className="px-2 py-2 text-right">{z.pedestrians}</td>
                  <td className="px-2 py-2 text-right">{z.occupancy_avg ?? "—"}</td>
                  <td className="px-2 py-2 text-right">{z.occupancy_max ?? "—"}</td>
                  <td className="px-2 py-2 text-right">{z.speed_avg_mps != null ? `${z.speed_avg_mps} m/s` : "—"}</td>
                  <td className="px-2 py-2 text-right">{z.events_total}</td>
                  <td className="px-4 py-2 text-right">
                    {z.risk.level} <span className="text-[var(--color-faint)]">({z.risk.score})</span>
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
