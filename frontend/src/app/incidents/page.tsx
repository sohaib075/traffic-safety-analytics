"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Search, SlidersHorizontal } from "lucide-react";
import { api, qs } from "@/lib/api";
import { EVENT_META, EVENT_TYPES, dayRange, fmtDate, fmtTime } from "@/lib/format";
import { useApp, useFetch } from "@/lib/state";
import type { CameraInfo, Incident } from "@/lib/types";
import { IncidentDetail } from "@/components/IncidentDetail";
import { Empty, ErrorNote, EventBadge, Panel, SeverityBadge, StatusBadge } from "@/components/ui";

const PAGE = 25;

interface Filters {
  q: string;
  types: string[];
  severities: string[];
  status: string[];
  camera: string;
  zone: string;
  vehicle_class: string;
  hour_from: string;
  hour_to: string;
}

const EMPTY: Filters = { q: "", types: [], severities: [], status: [], camera: "", zone: "", vehicle_class: "", hour_from: "", hour_to: "" };

function Chip({ on, onClick, children, color }: { on: boolean; onClick: () => void; children: React.ReactNode; color?: string }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full border px-2.5 py-0.5 text-xs transition-colors ${
        on ? "border-transparent text-white" : "border-[var(--color-line)] text-[var(--color-muted)] hover:text-white"
      }`}
      style={on ? { background: `${color ?? "#3b82f6"}33`, borderColor: color ?? "#3b82f6" } : undefined}
    >
      {children}
    </button>
  );
}

function Investigator() {
  const params = useSearchParams();
  const router = useRouter();
  const { day, live } = useApp();
  const [f, setF] = useState<Filters>(EMPTY);
  const [applied, setApplied] = useState<Filters>(EMPTY);
  const [page, setPage] = useState(0);
  const [data, setData] = useState<{ total: number; items: Incident[]; parsed_query: any } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showFilters, setShowFilters] = useState(false);
  const selected = params.get("id") ? Number(params.get("id")) : null;
  const { data: cameras } = useFetch<CameraInfo[]>("/api/cameras");

  const toggle = (key: "types" | "severities" | "status", v: string) =>
    setF((cur) => {
      const next = { ...cur, [key]: cur[key].includes(v) ? cur[key].filter((x) => x !== v) : [...cur[key], v] };
      setApplied(next);
      setPage(0);
      return next;
    });

  useEffect(() => {
    const p = qs({
      ...dayRange(day),
      q: applied.q,
      types: applied.types.join(","),
      severities: applied.severities.join(","),
      status: applied.status.join(","),
      camera: applied.camera,
      zone: applied.zone,
      vehicle_class: applied.vehicle_class,
      hour_from: applied.hour_from,
      hour_to: applied.hour_to,
      limit: PAGE,
      offset: page * PAGE,
    });
    api<{ total: number; items: Incident[]; parsed_query: any }>(`/api/incidents${p}`)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError(e.message));
  }, [applied, page, day, live.tick]);

  const select = (id: number) => router.replace(`/incidents?id=${id}`, { scroll: false });
  const zones = cameras?.flatMap((c) => c.zones.map((z) => ({ ...z, cam: c.name }))) ?? [];
  const pq = data?.parsed_query;

  return (
    <div className="mx-auto grid max-w-[1500px] gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,520px)]">
      <div className="min-w-0 space-y-3">
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setApplied(f);
            setPage(0);
          }}
        >
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-faint)]" />
            <input
              className="input w-full pl-9"
              placeholder='Try "serious events between 5 PM and 8 PM" or "wrong-way in the evening"'
              value={f.q}
              onChange={(e) => setF({ ...f, q: e.target.value })}
            />
          </div>
          <button className="btn btn-primary">Search</button>
          <button type="button" className="btn" onClick={() => setShowFilters((s) => !s)} aria-label="Filters">
            <SlidersHorizontal className="h-4 w-4" />
          </button>
        </form>

        {pq && (pq.types || pq.severities || pq.hour_from != null) && (
          <div className="text-xs text-[var(--color-muted)]">
            Interpreted as:{" "}
            {pq.types && <span className="mr-2">types = {pq.types.map((t: string) => EVENT_META[t]?.short ?? t).join(", ")}</span>}
            {pq.severities && <span className="mr-2">severity = {pq.severities.join("/")}</span>}
            {pq.hour_from != null && (
              <span>
                hours {String(pq.hour_from).padStart(2, "0")}:00–{String(pq.hour_to).padStart(2, "0")}:00
              </span>
            )}
          </div>
        )}

        <div className="flex flex-wrap gap-1.5">
          {EVENT_TYPES.map((t) => (
            <Chip key={t} on={f.types.includes(t)} onClick={() => toggle("types", t)} color={EVENT_META[t].color}>
              {EVENT_META[t].short}
            </Chip>
          ))}
        </div>

        {showFilters && (
          <div className="panel grid gap-3 p-3 text-xs sm:grid-cols-2 lg:grid-cols-3">
            <div>
              <div className="mb-1 text-[var(--color-muted)]">Severity</div>
              <div className="flex gap-1.5">
                {["high", "medium", "low"].map((s) => (
                  <Chip key={s} on={f.severities.includes(s)} onClick={() => toggle("severities", s)}>
                    {s}
                  </Chip>
                ))}
              </div>
            </div>
            <div>
              <div className="mb-1 text-[var(--color-muted)]">Review status</div>
              <div className="flex gap-1.5">
                {["new", "confirmed", "dismissed"].map((s) => (
                  <Chip key={s} on={f.status.includes(s)} onClick={() => toggle("status", s)}>
                    {s}
                  </Chip>
                ))}
              </div>
            </div>
            <label className="text-[var(--color-muted)]">
              Vehicle type
              <select className="input mt-1 w-full" value={f.vehicle_class} onChange={(e) => setF({ ...f, vehicle_class: e.target.value })}>
                <option value="">Any</option>
                {["car", "motorcycle", "bus", "truck", "bicycle", "person"].map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </label>
            <label className="text-[var(--color-muted)]">
              Camera
              <select className="input mt-1 w-full" value={f.camera} onChange={(e) => setF({ ...f, camera: e.target.value, zone: "" })}>
                <option value="">All cameras</option>
                {cameras?.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-[var(--color-muted)]">
              Zone / intersection
              <select className="input mt-1 w-full" value={f.zone} onChange={(e) => setF({ ...f, zone: e.target.value })}>
                <option value="">All zones</option>
                {zones
                  .filter((z) => !f.camera || cameras?.find((c) => c.id === f.camera)?.zones.some((x) => x.id === z.id))
                  .map((z) => (
                    <option key={`${z.cam}:${z.id}`} value={z.id}>
                      {z.name}
                    </option>
                  ))}
              </select>
            </label>
            <div className="text-[var(--color-muted)]">
              Time of day
              <div className="mt-1 flex items-center gap-1.5">
                <input className="input w-16" type="number" min={0} max={23} placeholder="from" value={f.hour_from} onChange={(e) => setF({ ...f, hour_from: e.target.value })} />
                <span>–</span>
                <input className="input w-16" type="number" min={1} max={24} placeholder="to" value={f.hour_to} onChange={(e) => setF({ ...f, hour_to: e.target.value })} />
                <span>h</span>
              </div>
            </div>
            <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-3">
              <button className="btn btn-primary" onClick={() => (setApplied(f), setPage(0))}>
                Apply
              </button>
              <button className="btn" onClick={() => (setF(EMPTY), setApplied(EMPTY), setPage(0))}>
                Reset
              </button>
            </div>
          </div>
        )}

        <ErrorNote error={error} />

        <Panel
          title={data ? `${data.total} incident${data.total === 1 ? "" : "s"}` : "Incidents"}
          right={
            data && data.total > PAGE ? (
              <div className="flex items-center gap-2 text-xs">
                <button className="btn py-0.5" disabled={page === 0} onClick={() => setPage(page - 1)}>
                  Prev
                </button>
                <span className="num text-[var(--color-muted)]">
                  {page + 1}/{Math.ceil(data.total / PAGE)}
                </span>
                <button className="btn py-0.5" disabled={(page + 1) * PAGE >= data.total} onClick={() => setPage(page + 1)}>
                  Next
                </button>
              </div>
            ) : null
          }
          bodyClass="p-0"
        >
          {data && data.items.length === 0 && <Empty>No incidents match these filters.</Empty>}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <tbody className="divide-y divide-[var(--color-line)]">
                {data?.items.map((i) => (
                  <tr
                    key={i.id}
                    onClick={() => select(i.id)}
                    className={`cursor-pointer hover:bg-[var(--color-panel-2)] ${selected === i.id ? "bg-[var(--color-panel-2)]" : ""}`}
                  >
                    <td className="num whitespace-nowrap px-4 py-2.5 text-[var(--color-muted)]">
                      <div className="text-[var(--color-ink)]">{fmtTime(i.occurred_at)}</div>
                      <div className="text-[11px]">{fmtDate(i.occurred_at)}</div>
                    </td>
                    <td className="px-2 py-2.5">
                      <EventBadge t={i.type} />
                      <div className="text-[11px] text-[var(--color-faint)]">#{i.id}</div>
                    </td>
                    <td className="hidden px-2 py-2.5 text-[var(--color-muted)] sm:table-cell">{i.zone_name ?? "—"}</td>
                    <td className="hidden px-2 py-2.5 text-xs text-[var(--color-muted)] md:table-cell">
                      {i.classes.map((c, n) => `${c} #${i.track_ids[n]}`).join(" + ")}
                    </td>
                    <td className="px-2 py-2.5">
                      <SeverityBadge s={i.severity} />
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <StatusBadge s={i.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      <div className="min-w-0 lg:sticky lg:top-[72px] lg:max-h-[calc(100vh-88px)] lg:overflow-y-auto">
        <Panel title="Incident detail">
          {selected ? (
            <IncidentDetail
              id={selected}
              onChange={(d) => setData((cur) => (cur ? { ...cur, items: cur.items.map((x) => (x.id === d.id ? d : x)) } : cur))}
            />
          ) : (
            <Empty>Select an incident to view evidence, measurements and the journey of each object.</Empty>
          )}
        </Panel>
      </div>
    </div>
  );
}

export default function Page() {
  return (
    <Suspense>
      <Investigator />
    </Suspense>
  );
}
