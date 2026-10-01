"use client";

import { useState } from "react";
import { Download, FileText } from "lucide-react";
import { api, qs } from "@/lib/api";
import { EVENT_META, EVENT_TYPES, dayRange, fmtHour, nf } from "@/lib/format";
import { useApp, useFetch } from "@/lib/state";
import type { CameraInfo, Summary } from "@/lib/types";
import { ErrorNote, PageHeader, Panel, RiskLevel } from "@/components/ui";

export default function ReportsPage() {
  const { day, extent } = useApp();
  const [reportDay, setReportDay] = useState<string>(day ?? extent.last?.slice(0, 10) ?? new Date().toISOString().slice(0, 10));
  const [camera, setCamera] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { data: cameras } = useFetch<CameraInfo[]>("/api/cameras");
  const { data: s } = useFetch<Summary>(`/api/stats/summary${qs({ ...dayRange(reportDay), camera })}`);

  const download = async () => {
    setBusy(true);
    setError(null);
    try {
      const blob = await api<Blob>(`/api/reports/daily.pdf${qs({ date: reportDay, camera })}`);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `roadguard-report-${reportDay}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <PageHeader title="Reports" subtitle="Export the daily road safety report as a PDF: KPIs, risk, hourly traffic, zone ranking and key evidence." />
      <Panel title="Daily road safety report" icon={FileText}>
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-xs text-[var(--color-muted)]">
            Date
            <input type="date" className="input mt-1 block" value={reportDay} onChange={(e) => setReportDay(e.target.value)} />
          </label>
          <label className="text-xs text-[var(--color-muted)]">
            Camera
            <select className="input mt-1 block" value={camera} onChange={(e) => setCamera(e.target.value)}>
              <option value="">All cameras</option>
              {cameras?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <button className="btn btn-primary" onClick={download} disabled={busy}>
            <Download className="h-4 w-4" /> {busy ? "Generating…" : "Export PDF"}
          </button>
        </div>
        <div className="mt-3">
          <ErrorNote error={error} />
        </div>
      </Panel>

      {s && (
        <Panel title="Preview">
          <div className="font-mono text-sm leading-7">
            <div className="mb-2 flex items-center gap-2 font-sans text-base font-semibold">
              <FileText className="h-4 w-4 text-[var(--color-accent)]" /> ROAD SAFETY REPORT · {reportDay}
            </div>
            <Row k="Traffic volume" v={nf.format(s.vehicles)} />
            <Row k="Pedestrians" v={nf.format(s.pedestrians)} />
            {EVENT_TYPES.map((t) => (
              <Row key={t} k={EVENT_META[t].label} v={s.events[t] ?? 0} />
            ))}
            <div className="my-2 border-t border-[var(--color-line)]" />
            <Row k="Risk indicator" v={<RiskLevel risk={s.risk} />} />
            <Row k="Highest observed risk zone" v={s.top_zone?.name ?? "—"} />
            <Row k="Peak traffic hour" v={s.peak_hour ? fmtHour(s.peak_hour) : "—"} />
          </div>
        </Panel>
      )}
    </div>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex justify-between border-b border-dashed border-[var(--color-line)]">
      <span className="text-[var(--color-muted)]">{k}</span>
      <span className="num">{v}</span>
    </div>
  );
}
