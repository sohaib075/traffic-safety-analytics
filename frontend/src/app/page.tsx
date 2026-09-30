"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { qs } from "@/lib/api";
import { CLASS_COLOR, LEVEL_COLOR, dayRange, fmtHour, fmtTime, nf } from "@/lib/format";
import { useApp, useFetch } from "@/lib/state";
import type { Bucket, CameraInfo, Incident, Summary, ZoneStat } from "@/lib/types";
import { LiveFeed } from "@/components/LiveFeed";
import { ZoneMap } from "@/components/ZoneMap";
import { Empty, EventBadge, Kpi, Panel, RiskBreakdown, RiskLevel, SeverityBadge } from "@/components/ui";

const VIOLATIONS = ["red_light", "wrong_way", "helmet_violation", "illegal_stop"];

export default function Dashboard() {
  const { day, live } = useApp();
  const range = dayRange(day);
  const q = qs(range);
  const { data: summary } = useFetch<Summary>(`/api/stats/summary${q}`, [live.tick]);
  const { data: zones } = useFetch<ZoneStat[]>(`/api/stats/zones${q}`, [live.tick]);
  const { data: ts } = useFetch<{ buckets: Bucket[] }>(`/api/stats/timeseries${qs({ ...range, bucket: "hour" })}`, [live.tick]);
  const { data: recent } = useFetch<{ items: Incident[] }>(`/api/incidents${qs({ ...range, limit: 8, status: "new,confirmed" })}`, [live.tick]);
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

  const violations = summary ? VIOLATIONS.reduce((a, k) => a + (summary.events[k] ?? 0), 0) : 0;
  const newIds = new Set(live.incidents.slice(0, 5).map((i) => i.id));

  return (
    <div className="mx-auto max-w-[1500px] space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Kpi label="Vehicles" value={summary ? nf.format(summary.vehicles) : "—"} sub={summary ? `${nf.format(summary.pedestrians)} pedestrians` : undefined} />
        <Kpi label="Violations" value={summary ? violations : "—"} sub="red-light · wrong-way · helmet · stopping" />
        <Kpi label="Near-misses" value={summary?.events.near_miss ?? (summary ? 0 : "—")} sub="potential, vehicle–vehicle" color="#f97316" />
        <Kpi label="Ped conflicts" value={summary?.events.ped_conflict ?? (summary ? 0 : "—")} sub="potential, vehicle–pedestrian" color="#ec4899" />
        <div className="panel col-span-2 px-4 py-3 lg:col-span-1">
          <div className="panel-title">Risk indicator</div>
          {summary ? (
            <>
              <div className="mt-1 flex items-baseline gap-2">
                <RiskLevel risk={summary.risk} big />
                <span className="num text-xs text-[var(--color-muted)]">score {summary.risk.score}</span>
              </div>
              <div className="text-xs text-[var(--color-muted)]">
                Peak {summary.peak_hour ? fmtHour(summary.peak_hour) : "—"}
                {summary.top_zone ? ` · hotspot ${summary.top_zone.name}` : ""}
              </div>
            </>
          ) : (
            <div className="mt-1 text-2xl">—</div>
          )}
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.35fr_1fr]">
        <Panel
          title="Live traffic"
          right={
            cameras && cameras.length > 1 ? (
              <select className="input py-0.5 text-xs" value={camera?.id} onChange={(e) => setCamId(e.target.value)}>
                {cameras.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            ) : null
          }
          bodyClass="p-3"
        >
          <LiveFeed camera={camera} />
          {camera && live.progress[camera.id] && (
            <div className="mt-2 flex flex-wrap gap-3 text-xs text-[var(--color-muted)]">
              {Object.entries(live.progress[camera.id].live.objects).map(([k, v]) => (
                <span key={k}>
                  <span style={{ color: CLASS_COLOR[k] }}>●</span> {k} {v}
                </span>
              ))}
              {Object.entries(live.progress[camera.id].live.signals).map(([k, v]) => (
                <span key={k}>signal {k}: <b className={v === "red" ? "text-red-400" : "text-emerald-400"}>{v}</b></span>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Road risk map" right={<Link href="/map" className="text-xs text-[var(--color-accent)]">Open map →</Link>} bodyClass="p-3">
          {zones ? <ZoneMap zones={zones} height={330} /> : <div className="h-[330px]" />}
          <div className="mt-2 flex gap-3 text-[11px] text-[var(--color-muted)]">
            {Object.entries(LEVEL_COLOR).map(([k, c]) => (
              <span key={k} className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full" style={{ background: c }} /> {k}
              </span>
            ))}
            <span className="ml-auto">observed event density</span>
          </div>
        </Panel>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1.35fr_1fr]">
        <Panel title="Recent incidents" right={<Link href="/incidents" className="text-xs text-[var(--color-accent)]">Investigate →</Link>} bodyClass="p-0">
          {recent && recent.items.length === 0 && <Empty>No incidents in this range.</Empty>}
          <ul className="divide-y divide-[var(--color-line)]">
            {recent?.items.map((i) => (
              <li key={i.id}>
                <Link
                  href={`/incidents?id=${i.id}`}
                  className={`grid grid-cols-[auto_1fr_auto] items-center gap-3 px-4 py-2.5 hover:bg-[var(--color-panel-2)] sm:grid-cols-[1fr_1fr_auto_auto] ${newIds.has(i.id) ? "flash" : ""}`}
                >
                  <EventBadge t={i.type} />
                  <span className="truncate text-sm text-[var(--color-muted)]">{i.zone_name ?? i.camera_id}</span>
                  <span className="hidden sm:block">
                    <SeverityBadge s={i.severity} />
                  </span>
                  <span className="num text-sm">{fmtTime(i.occurred_at, false)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </Panel>

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-1">
          <Panel title="Risk breakdown">
            {summary ? <RiskBreakdown risk={summary.risk} /> : null}
            {summary && <p className="mt-3 text-[11px] leading-snug text-[var(--color-faint)]">{summary.risk.method}</p>}
          </Panel>
          <Panel title="Traffic by hour" bodyClass="p-2">
            {ts && ts.buckets.length > 0 ? (
              <ResponsiveContainer width="100%" height={170}>
                <BarChart data={ts.buckets.map((b) => ({ ...b, hour: fmtHour(b.start) }))} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}>
                  <CartesianGrid stroke="#1f2a3a" vertical={false} />
                  <XAxis dataKey="hour" tick={{ fill: "#8b98ab", fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: "#8b98ab", fontSize: 11 }} axisLine={false} tickLine={false} allowDecimals={false} />
                  <Tooltip contentStyle={{ background: "#151d2b", border: "1px solid #1f2a3a", borderRadius: 8, fontSize: 12 }} cursor={{ fill: "#ffffff08" }} />
                  {["car", "motorcycle", "bus", "truck", "bicycle"].map((k) => (
                    <Bar isAnimationActive={false} key={k} dataKey={k} stackId="v" fill={CLASS_COLOR[k]} />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <Empty>No traffic in range.</Empty>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
