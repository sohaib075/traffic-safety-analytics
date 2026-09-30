"use client";

import { useEffect, useState } from "react";
import { Check, Clock, Film, MapPin, X as XIcon } from "lucide-react";
import { api, mediaUrl } from "@/lib/api";
import { CLASS_COLOR, eventLabel, fmtDate, fmtTime } from "@/lib/format";
import { useApp } from "@/lib/state";
import type { Incident, Journey } from "@/lib/types";
import { ErrorNote, EventBadge, SeverityBadge, StatusBadge } from "./ui";

const METRIC_LABELS: Record<string, string> = {
  ttc_s: "Time-to-conflict (s)",
  distance_m: "Separation (m)",
  closing_speed_mps: "Closing speed (m/s)",
  speed_a_mps: "Speed A (m/s)",
  speed_b_mps: "Speed B (m/s)",
  speed_mps: "Speed (m/s)",
  direction_cos: "Direction cos",
  dwell_s: "Dwell (s)",
  vehicles: "Vehicles",
  avg_speed_mps: "Avg speed (m/s)",
  duration_s: "Duration (s)",
  lane: "Lane",
  stop_line: "Stop line",
  signal: "Signal",
  calibrated: "Calibrated geometry",
};

/** Snapshot with the involved objects' trajectories drawn on top (journey reconstruction). */
function JourneyOverlay({ src, journeys }: { src: string; journeys: Journey[] }) {
  return (
    <div className="relative">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={src} alt="Incident evidence frame" className="w-full rounded-md" />
      <svg viewBox="0 0 1 1" preserveAspectRatio="none" className="pointer-events-none absolute inset-0 h-full w-full">
        {journeys.map((j) => {
          const c = CLASS_COLOR[j.cls] ?? "#fff";
          const pts = j.path.map(([, x, y]) => `${x},${y}`).join(" ");
          const first = j.path[0];
          const last = j.path[j.path.length - 1];
          return (
            <g key={j.track_id}>
              <polyline points={pts} fill="none" stroke={c} strokeWidth={2.5} strokeDasharray="6 4" vectorEffect="non-scaling-stroke" />
              {first && <circle cx={first[1]} cy={first[2]} r={0.008} fill={c} />}
              {last && <circle cx={last[1]} cy={last[2]} r={0.008} fill="white" stroke={c} strokeWidth={0.004} />}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function IncidentDetail({ id, onChange }: { id: number; onChange?: (i: Incident) => void }) {
  const { can, live } = useApp();
  const [inc, setInc] = useState<Incident | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notes, setNotes] = useState("");
  const [view, setView] = useState<"clip" | "journey">("clip");

  useEffect(() => {
    setInc(null);
    api<Incident>(`/api/incidents/${id}`)
      .then((d) => {
        setInc(d);
        setNotes(d.notes);
        setError(null);
      })
      .catch((e) => setError(e.message));
  }, [id]);

  // pick up "clip ready" updates pushed over the WebSocket
  useEffect(() => {
    const upd = live.incidents.find((x) => x.id === id);
    if (upd && inc && upd.clip_ready && !inc.clip_ready) setInc({ ...inc, ...upd, journeys: inc.journeys });
  }, [live.incidents, id, inc]);

  const review = async (status?: Incident["status"]) => {
    try {
      const d = await api<Incident>(`/api/incidents/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ status, notes }),
      });
      setInc({ ...d, journeys: inc?.journeys });
      onChange?.(d);
    } catch (e: any) {
      setError(e.message);
    }
  };

  if (error) return <ErrorNote error={error} />;
  if (!inc) return <div className="p-6 text-sm text-[var(--color-muted)]">Loading incident…</div>;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-lg font-semibold">Incident #{inc.id}</h3>
        <SeverityBadge s={inc.severity} />
        <StatusBadge s={inc.status} />
      </div>

      <div className="flex gap-1 text-xs">
        <button className={`btn py-1 ${view === "clip" ? "border-[var(--color-accent)]" : ""}`} onClick={() => setView("clip")}>
          <Film className="h-3.5 w-3.5" /> Evidence clip
        </button>
        <button className={`btn py-1 ${view === "journey" ? "border-[var(--color-accent)]" : ""}`} onClick={() => setView("journey")}>
          <MapPin className="h-3.5 w-3.5" /> Journey overlay
        </button>
      </div>

      {view === "clip" ? (
        inc.clip_url ? (
          <video key={inc.clip_url} src={mediaUrl(inc.clip_url)} controls autoPlay muted loop playsInline className="w-full rounded-md bg-black" poster={mediaUrl(inc.snapshot_url)} />
        ) : (
          <div className="relative">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            {inc.snapshot_url && <img src={mediaUrl(inc.snapshot_url)} alt="Evidence frame" className="w-full rounded-md" />}
            <div className="absolute bottom-2 left-2 rounded bg-black/70 px-2 py-1 text-xs text-[var(--color-muted)]">
              {!can("investigate") ? "Clip access requires the operator role" : inc.clip_ready ? "" : "Clip still recording…"}
            </div>
          </div>
        )
      ) : inc.snapshot_url ? (
        <JourneyOverlay src={mediaUrl(inc.snapshot_url)!} journeys={inc.journeys ?? []} />
      ) : null}

      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
        <dt className="text-[var(--color-muted)]">Event</dt>
        <dd>
          <EventBadge t={inc.type} short={false} />
        </dd>
        <dt className="text-[var(--color-muted)]">Time</dt>
        <dd className="num flex items-center gap-1.5">
          <Clock className="h-3.5 w-3.5 text-[var(--color-faint)]" />
          {fmtDate(inc.occurred_at)} {fmtTime(inc.occurred_at)}
          <span className="text-[var(--color-faint)]">(video t={inc.video_t.toFixed(1)}s)</span>
        </dd>
        <dt className="text-[var(--color-muted)]">Zone</dt>
        <dd>{inc.zone_name ?? "—"}</dd>
        <dt className="text-[var(--color-muted)]">Camera</dt>
        <dd>{inc.camera_id}</dd>
        <dt className="text-[var(--color-muted)]">Objects</dt>
        <dd className="flex flex-wrap gap-1.5">
          {inc.track_ids.map((t, i) => (
            <span key={t} className="rounded bg-[var(--color-panel-2)] px-1.5 py-0.5 text-xs">
              <span style={{ color: CLASS_COLOR[inc.classes[i]] }}>{inc.classes[i]}</span> #{t}
            </span>
          ))}
          {inc.track_ids.length === 0 && "—"}
        </dd>
        <dt className="text-[var(--color-muted)]">Confidence</dt>
        <dd className="num">{(inc.confidence * 100).toFixed(0)}%</dd>
      </dl>

      <p className="rounded-md bg-[var(--color-panel-2)] px-3 py-2 text-sm">{inc.description}</p>

      {Object.keys(inc.metrics).length > 0 && (
        <div>
          <div className="panel-title mb-1.5">Measurements</div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
            {Object.entries(inc.metrics).map(([k, v]) => (
              <div key={k}>
                <dt className="text-[var(--color-faint)]">{METRIC_LABELS[k] ?? k}</dt>
                <dd className="num">{String(v)}</dd>
              </div>
            ))}
          </dl>
          {inc.metrics.calibrated === false && (
            <p className="mt-1.5 text-[11px] text-[var(--color-faint)]">
              Uncalibrated camera: distances and speeds are approximate (uniform scale).
            </p>
          )}
        </div>
      )}

      {inc.journeys && inc.journeys.length > 0 && (
        <div>
          <div className="panel-title mb-1.5">Journey reconstruction</div>
          <div className="space-y-2">
            {inc.journeys.map((j) => (
              <div key={j.track_id} className="rounded-md border border-[var(--color-line)] p-2.5 text-xs">
                <div className="mb-1 flex items-center gap-2">
                  <span className="font-medium" style={{ color: CLASS_COLOR[j.cls] }}>
                    {j.cls} #{j.track_id}
                  </span>
                  <span className="num text-[var(--color-faint)]">
                    {fmtTime(j.first_seen)} → {fmtTime(j.last_seen)} · max {j.max_speed_mps.toFixed(1)} m/s
                  </span>
                </div>
                <div className="flex flex-wrap items-center gap-1 text-[var(--color-muted)]">
                  <span>Entry</span>
                  {j.route.map((r) => (
                    <span key={r.zone_id}>
                      → <span className="text-[var(--color-ink)]">{r.name}</span>
                    </span>
                  ))}
                  <span>→ Exit</span>
                </div>
                {j.events.length > 0 && (
                  <div className="mt-1 text-[var(--color-muted)]">Events: {j.events.map((e) => eventLabel(e, true)).join(", ")}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {can("review") && (
        <div className="space-y-2 border-t border-[var(--color-line)] pt-3">
          <div className="panel-title">Human review</div>
          <textarea
            className="input h-16 w-full resize-none"
            placeholder="Reviewer notes…"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          <div className="flex flex-wrap gap-2">
            <button className="btn" onClick={() => review("confirmed")}>
              <Check className="h-3.5 w-3.5 text-red-400" /> Confirm
            </button>
            <button className="btn" onClick={() => review("dismissed")}>
              <XIcon className="h-3.5 w-3.5" /> Dismiss (false positive)
            </button>
            <button className="btn" onClick={() => review(undefined)}>
              Save notes
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
