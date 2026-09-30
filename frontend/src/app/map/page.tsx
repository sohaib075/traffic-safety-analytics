"use client";

import Link from "next/link";
import { useState } from "react";
import { qs } from "@/lib/api";
import { EVENT_META, EVENT_TYPES, LEVEL_COLOR, dayRange } from "@/lib/format";
import { useApp, useFetch } from "@/lib/state";
import type { ZoneStat } from "@/lib/types";
import { ZoneMap } from "@/components/ZoneMap";
import { Panel, RiskBreakdown, RiskLevel } from "@/components/ui";

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
    <div className="mx-auto max-w-[1500px] space-y-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-xs text-[var(--color-muted)]">Heatmap layer</span>
        {["risk", ...EVENT_TYPES].map((m) => (
          <button
            key={m}
            onClick={() => setMetric(m)}
            className={`rounded-full border px-2.5 py-0.5 text-xs ${
              metric === m ? "border-[var(--color-accent)] bg-[var(--color-accent)]/15 text-white" : "border-[var(--color-line)] text-[var(--color-muted)]"
            }`}
          >
            {m === "risk" ? "Overall risk" : EVENT_META[m].short}
          </button>
        ))}
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
        <Panel bodyClass="p-2">
          {zones ? <ZoneMap zones={zones} metric={metric} height="calc(100vh - 190px)" onSelect={setSel} /> : null}
        </Panel>

        <div className="space-y-4">
          {current && (
            <Panel title="Selected zone">
              <div className="flex items-baseline justify-between">
                <div>
                  <div className="text-lg font-semibold">{current.name}</div>
                  <div className="text-xs text-[var(--color-muted)]">
                    {current.camera_name} · {current.type}
                  </div>
                </div>
                <RiskLevel risk={current.risk} />
              </div>
              <div className="num my-3 grid grid-cols-3 gap-2 text-center text-xs">
                <div className="rounded bg-[var(--color-panel-2)] p-2">
                  <div className="text-lg text-[var(--color-ink)]">{current.vehicles}</div>vehicles
                </div>
                <div className="rounded bg-[var(--color-panel-2)] p-2">
                  <div className="text-lg text-[var(--color-ink)]">{current.pedestrians}</div>pedestrians
                </div>
                <div className="rounded bg-[var(--color-panel-2)] p-2">
                  <div className="text-lg text-[var(--color-ink)]">{current.events_total}</div>events
                </div>
              </div>
              <RiskBreakdown risk={current.risk} />
              <div className="mt-3 text-xs text-[var(--color-muted)]">
                Avg occupancy {current.occupancy_avg ?? "—"} veh · peak {current.occupancy_max ?? "—"} · avg speed{" "}
                {current.speed_avg_mps != null ? `${current.speed_avg_mps} m/s` : "—"}
              </div>
              <Link href={`/incidents`} className="mt-3 inline-block text-xs text-[var(--color-accent)]">
                Investigate incidents →
              </Link>
            </Panel>
          )}

          <Panel title="Zone ranking" bodyClass="p-0">
            <ul className="divide-y divide-[var(--color-line)] text-sm">
              {ranked.map((z, n) => (
                <li key={`${z.camera_id}:${z.id}`}>
                  <button onClick={() => setSel(z)} className="flex w-full items-center gap-3 px-4 py-2 text-left hover:bg-[var(--color-panel-2)]">
                    <span className="num w-5 text-[var(--color-faint)]">{n + 1}</span>
                    <span className="h-2.5 w-2.5 rounded-full" style={{ background: LEVEL_COLOR[z.risk.level] }} />
                    <span className="flex-1 truncate">{z.name}</span>
                    <span className="num text-xs text-[var(--color-muted)]">
                      {metric === "risk" ? `${z.events_total} ev · ${z.risk.score}` : `${z.events[metric] ?? 0}`}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>
    </div>
  );
}
