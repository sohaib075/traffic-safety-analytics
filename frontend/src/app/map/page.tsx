"use client";

import Link from "next/link";
import { useState } from "react";
import { qs } from "@/lib/api";
import { EVENT_META, EVENT_TYPES, LEVEL_COLOR, dayRange } from "@/lib/format";
import { useApp, useFetch } from "@/lib/state";
import type { ZoneStat } from "@/lib/types";
import { ZoneMap } from "@/components/ZoneMap";
import { ArrowRight, ListOrdered, MapPin } from "lucide-react";
import { PageHeader, Panel, RiskBreakdown, RiskLevel } from "@/components/ui";

export default function MapPage() {
  const { day, live } = useApp();
  const [metric, setMetric] = useState<string>("risk");
  const [sel, setSel] = useState<ZoneStat | null>(null);
  const { data: zones } = useFetch<ZoneStat[]>(`/api/stats/zones${qs(dayRange(day))}`, [live.tick]);

  const ranked = [...(zones ?? [])].sort((a, b) =>
    metric === "risk" ? b.risk.score - a.risk.score || b.events_total - a.events_total : (b.events[metric] ?? 0) - (a.events[metric] ?? 0),
  );
  const current = sel ? zones?.find((z) => z.id === sel.id && z.camera_id === sel.camera_id) ?? sel : ranked[0];

  return (
    <div className="mx-auto max-w-[1500px] space-y-4">
      <PageHeader title="Risk map" subtitle="Zones sized and coloured by observed potential safety events. Click a zone for its breakdown." />
      <div className="flex flex-wrap items-center gap-2">
        <span className="eyebrow mr-1">Layer</span>
        {["risk", ...EVENT_TYPES].map((m) => (
          <button
            key={m}
            onClick={() => setMetric(m)}
            aria-pressed={metric === m}
            className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
              metric === m ? "is-active shadow-sm" : "border-[var(--color-line-strong)] bg-white text-[var(--color-muted)] hover:border-slate-400 hover:text-[var(--color-ink)]"
            }`}
          >
            {m !== "risk" && <span className="h-2 w-2 rounded-full" style={{ background: EVENT_META[m].color }} />}
            {m === "risk" ? "Overall risk" : EVENT_META[m].short}
          </button>
        ))}
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_380px]">
        <Panel bodyClass="p-2">
          <div className="overflow-hidden rounded-xl">
            {zones ? <ZoneMap zones={zones} metric={metric} height="calc(100vh - 230px)" onSelect={setSel} /> : null}
          </div>
        </Panel>

        <div className="space-y-6">
          {current && (
            <Panel title="Selected zone" icon={MapPin}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-lg font-semibold tracking-tight">{current.name}</div>
                  <div className="text-xs capitalize text-[var(--color-faint)]">
                    {current.camera_name} · {current.type}
                  </div>
                </div>
                <RiskLevel risk={current.risk} />
              </div>
              <div className="num my-4 grid grid-cols-3 gap-2 text-center text-xs text-[var(--color-muted)]">
                {[
                  [current.vehicles, "vehicles"],
                  [current.pedestrians, "pedestrians"],
                  [current.events_total, "events"],
                ].map(([v, l]) => (
                  <div key={l as string} className="rounded-xl bg-[var(--color-panel-2)] px-2 py-3">
                    <div className="text-xl font-semibold text-[var(--color-ink)]">{v}</div>
                    {l}
                  </div>
                ))}
              </div>
              <RiskBreakdown risk={current.risk} />
              <div className="mt-4 text-xs text-[var(--color-faint)]">
                Avg occupancy {current.occupancy_avg ?? "—"} veh · peak {current.occupancy_max ?? "—"} · avg speed{" "}
                {current.speed_avg_mps != null ? `${current.speed_avg_mps} m/s` : "—"}
              </div>
              <Link href={`/incidents`} className="mt-4 inline-flex items-center gap-1 text-xs font-semibold text-[var(--color-accent)] hover:underline">
                Investigate incidents <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </Panel>
          )}

          <Panel title="Zone ranking" icon={ListOrdered} bodyClass="p-0">
            <ul className="divide-y divide-[var(--color-line)] text-sm">
              {ranked.map((z, n) => {
                const selected = current && z.id === current.id && z.camera_id === current.camera_id;
                return (
                  <li key={`${z.camera_id}:${z.id}`}>
                    <button
                      onClick={() => setSel(z)}
                      className={`flex w-full items-center gap-3 px-5 py-2.5 text-left transition-colors hover:bg-[var(--color-panel-2)] ${selected ? "bg-[var(--color-accent-soft)]" : ""}`}
                    >
                      <span className={`num grid h-6 w-6 place-items-center rounded-full text-xs font-semibold ${n < 3 ? "bg-slate-900 text-white" : "bg-[var(--color-panel-2)] text-[var(--color-muted)]"}`}>{n + 1}</span>
                      <span className="h-2.5 w-2.5 rounded-full" style={{ background: LEVEL_COLOR[z.risk.level] }} />
                      <span className="flex-1 truncate font-medium">{z.name}</span>
                      <span className="num text-xs text-[var(--color-faint)]">
                        {metric === "risk" ? `${z.events_total} events · ${z.risk.score}` : `${z.events[metric] ?? 0}`}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </Panel>
        </div>
      </div>
    </div>
  );
}
