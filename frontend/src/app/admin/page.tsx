"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Play, Square, Upload } from "lucide-react";
import { api, mediaUrl } from "@/lib/api";
import { fmtDate, fmtTime, localIso } from "@/lib/format";
import { useApp, useFetch } from "@/lib/state";
import type { CameraInfo, Job } from "@/lib/types";
import { ErrorNote, Panel, StatusBadge } from "@/components/ui";

export default function AdminPage() {
  const { can, live } = useApp();
  const { data: cameras, reload: reloadCams } = useFetch<CameraInfo[]>("/api/cameras", [live.tick]);
  const { data: jobs, reload: reloadJobs } = useFetch<Job[]>("/api/jobs", [live.tick]);

  // refresh the job list while anything is processing
  useEffect(() => {
    if (!Object.keys(live.progress).length) return;
    const t = setInterval(reloadJobs, 3000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [Object.keys(live.progress).length]);

  return (
    <div className="mx-auto max-w-[1400px] space-y-4">
      <div className="grid gap-4 xl:grid-cols-[420px_1fr]">
        <ProcessForm cameras={cameras ?? []} onSubmitted={reloadJobs} />
        <Panel title="Processing jobs" bodyClass="p-0">
          <div className="max-h-[420px] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-[var(--color-panel)] text-left text-xs text-[var(--color-muted)]">
                <tr className="border-b border-[var(--color-line)]">
                  <th className="px-4 py-2 font-medium">Job</th>
                  <th className="px-2 py-2 font-medium">Camera / source</th>
                  <th className="px-2 py-2 font-medium">Progress</th>
                  <th className="px-2 py-2 font-medium">Result</th>
                  <th className="px-4 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-line)]">
                {jobs?.map((j) => {
                  const p = live.progress[j.camera_id]?.job_id === j.id ? live.progress[j.camera_id] : j.live;
                  const pct = Math.round(((p?.progress ?? j.progress) || 0) * 100);
                  const ev = (j.summary as any)?.events as Record<string, number> | undefined;
                  return (
                    <tr key={j.id}>
                      <td className="num px-4 py-2">
                        #{j.id}
                        <div>
                          <StatusBadge s={j.status} />
                        </div>
                      </td>
                      <td className="px-2 py-2">
                        <div>{j.camera_id}</div>
                        <div className="max-w-[220px] truncate text-xs text-[var(--color-faint)]" title={j.source}>
                          {j.source} · starts {fmtDate(j.video_start)} {fmtTime(j.video_start, false)}
                        </div>
                      </td>
                      <td className="w-40 px-2 py-2">
                        <div className="h-1.5 rounded-full bg-[var(--color-panel-2)]">
                          <div className="h-1.5 rounded-full bg-[var(--color-accent)]" style={{ width: `${pct}%` }} />
                        </div>
                        <div className="num mt-1 text-[11px] text-[var(--color-muted)]">
                          {pct}% · {p?.proc_fps ?? j.proc_fps ?? "—"} fps
                        </div>
                      </td>
                      <td className="px-2 py-2 text-xs text-[var(--color-muted)]">
                        {j.error ? (
                          <span className="text-red-300">{j.error}</span>
                        ) : ev ? (
                          Object.entries(ev).map(([k, v]) => `${k} ${v}`).join(" · ") || "no events"
                        ) : (
                          "—"
                        )}
                        {j.annotated_url && (
                          <a className="ml-2 text-[var(--color-accent)]" href={mediaUrl(j.annotated_url)} target="_blank" rel="noreferrer">
                            annotated video
                          </a>
                        )}
                      </td>
                      <td className="px-4 py-2 text-right">
                        {j.status === "running" && (
                          <button
                            className="btn py-0.5 text-xs"
                            onClick={() => api(`/api/jobs/${j.id}/cancel`, { method: "POST" }).then(reloadJobs)}
                          >
                            <Square className="h-3 w-3" /> Stop
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>

      <CameraEditor cameras={cameras ?? []} canEdit={can("configure")} onSaved={reloadCams} />

      {can("manage_users") && <Audit />}
    </div>
  );
}

function ProcessForm({ cameras, onSubmitted }: { cameras: CameraInfo[]; onSubmitted: () => void }) {
  const [camera, setCamera] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [path, setPath] = useState("");
  const [start, setStart] = useState(() => localIso(new Date()).slice(0, 16));
  const [realtime, setRealtime] = useState(false);
  const [maxSeconds, setMaxSeconds] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!camera && cameras[0]) setCamera(cameras[0].id);
  }, [cameras, camera]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setMsg(null);
    const fd = new FormData();
    fd.set("camera_id", camera);
    if (file) fd.set("file", file);
    else fd.set("path", path);
    fd.set("video_start", `${start}:00`);
    fd.set("realtime", String(realtime));
    if (maxSeconds) fd.set("max_seconds", maxSeconds);
    try {
      const r = await api<{ job_id: number }>("/api/jobs", { method: "POST", body: fd });
      setMsg(`Job #${r.job_id} started — watch it live on the Command page.`);
      onSubmitted();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title="Process video">
      <form onSubmit={submit} className="space-y-3 text-xs text-[var(--color-muted)]">
        <label className="block">
          Camera
          <select className="input mt-1 w-full" value={camera} onChange={(e) => setCamera(e.target.value)}>
            {cameras.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          Upload video file
          <input type="file" accept="video/*" className="input mt-1 w-full" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <label className="block">
          …or a path / stream URL on the server
          <input className="input mt-1 w-full" placeholder="data/samples/car-detection.mp4 or rtsp://…" value={path} onChange={(e) => setPath(e.target.value)} disabled={!!file} />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            Wall-clock time of first frame
            <input type="datetime-local" className="input mt-1 w-full" value={start} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label className="block">
            Limit (seconds, optional)
            <input type="number" className="input mt-1 w-full" value={maxSeconds} onChange={(e) => setMaxSeconds(e.target.value)} />
          </label>
        </div>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={realtime} onChange={(e) => setRealtime(e.target.checked)} />
          Pace playback to real time (simulates a live camera)
        </label>
        <button className="btn btn-primary" disabled={busy || !camera || (!file && !path)}>
          {file ? <Upload className="h-4 w-4" /> : <Play className="h-4 w-4" />} {busy ? "Submitting…" : "Start processing"}
        </button>
        {msg && <p className="text-emerald-300">{msg}</p>}
        <ErrorNote error={error} />
      </form>
    </Panel>
  );
}

type Pt = [number, number];

function CameraEditor({ cameras, canEdit, onSaved }: { cameras: CameraInfo[]; canEdit: boolean; onSaved: () => void }) {
  const [id, setId] = useState("");
  const [text, setText] = useState("");
  const [cfg, setCfg] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [frameOk, setFrameOk] = useState(true);

  useEffect(() => {
    if (!id && cameras[0]) setId(cameras[0].id);
  }, [cameras, id]);

  useEffect(() => {
    if (!id) return;
    setFrameOk(true);
    api<any>(`/api/cameras/${id}/config`).then((c) => {
      setCfg(c);
      setText(JSON.stringify(c, null, 2));
    });
  }, [id]);

  const parse = (t: string) => {
    setText(t);
    setSaved(false);
    try {
      setCfg(JSON.parse(t));
      setError(null);
    } catch {
      setError("Invalid JSON");
    }
  };

  const save = async () => {
    try {
      await api(`/api/cameras/${id}/config`, { method: "PUT", body: text });
      setSaved(true);
      setError(null);
      onSaved();
    } catch (e: any) {
      setError(e.message);
    }
  };

  const poly = (p: Pt[]) => p.map(([x, y]) => `${x},${y}`).join(" ");

  return (
    <Panel
      title="Camera scene configuration"
      right={
        <select className="input py-0.5 text-xs" value={id} onChange={(e) => setId(e.target.value)}>
          {cameras.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      }
    >
      <div className="grid gap-4 xl:grid-cols-2">
        <div>
          <div className="relative overflow-hidden rounded-md bg-black">
            {frameOk ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={mediaUrl(`/api/cameras/${id}/frame`)} alt="Camera frame" className="w-full" onError={() => setFrameOk(false)} />
            ) : (
              <div className="grid aspect-video place-items-center text-xs text-[var(--color-muted)]">Process a video once to see a reference frame</div>
            )}
            {cfg && (
              <svg viewBox="0 0 1 1" preserveAspectRatio="none" className="pointer-events-none absolute inset-0 h-full w-full">
                {cfg.zones?.map((z: any) => (
                  <polygon key={z.id} points={poly(z.polygon)} fill={z.type === "no_stopping" ? "#ef444433" : z.type === "crosswalk" ? "#ffffff22" : "#3b82f622"} stroke="#e5e7eb" strokeWidth={1} vectorEffect="non-scaling-stroke" />
                ))}
                {cfg.lanes?.map((l: any) => (
                  <polygon key={l.id} points={poly(l.polygon)} fill="none" stroke="#a855f7" strokeDasharray="4 3" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
                ))}
                {cfg.stop_lines?.map((s: any) => (
                  <line key={s.id} x1={s.line[0][0]} y1={s.line[0][1]} x2={s.line[1][0]} y2={s.line[1][1]} stroke="#ef4444" strokeWidth={3} vectorEffect="non-scaling-stroke" />
                ))}
                {cfg.counting_lines?.map((s: any) => (
                  <line key={s.id} x1={s.line[0][0]} y1={s.line[0][1]} x2={s.line[1][0]} y2={s.line[1][1]} stroke="#22d3ee" strokeWidth={2} vectorEffect="non-scaling-stroke" />
                ))}
              </svg>
            )}
          </div>
          <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-[var(--color-muted)]">
            <span>▭ zones</span>
            <span className="text-purple-400">┅ lanes (direction in config)</span>
            <span className="text-red-400">━ stop lines</span>
            <span className="text-cyan-400">━ counting lines</span>
            <span>Coordinates are normalized 0–1.</span>
          </div>
        </div>
        <div className="flex flex-col gap-2">
          <textarea
            className="input h-[360px] w-full resize-y font-mono text-[11px] leading-snug"
            value={text}
            onChange={(e) => parse(e.target.value)}
            readOnly={!canEdit}
            spellCheck={false}
          />
          <div className="flex items-center gap-2">
            {canEdit ? (
              <button className="btn btn-primary" onClick={save} disabled={!!error && error === "Invalid JSON"}>
                Save configuration
              </button>
            ) : (
              <span className="text-xs text-[var(--color-muted)]">Read-only — configuration requires the admin role.</span>
            )}
            {saved && <span className="text-xs text-emerald-300">Saved. Applies to the next processing job.</span>}
          </div>
          <ErrorNote error={error} />
        </div>
      </div>
    </Panel>
  );
}

function Audit() {
  const { data } = useFetch<{ ts: string; username: string; action: string; detail: string }[]>("/api/audit?limit=100");
  return (
    <Panel title="Audit log" right={<Link href="/users" className="text-xs text-[var(--color-accent)]">Manage users →</Link>} bodyClass="p-0">
      <div className="max-h-72 overflow-auto">
        <table className="w-full text-xs">
          <tbody className="divide-y divide-[var(--color-line)]">
            {data?.map((a, i) => (
              <tr key={i}>
                <td className="num whitespace-nowrap px-4 py-1.5 text-[var(--color-muted)]">
                  {fmtDate(a.ts)} {fmtTime(a.ts)}
                </td>
                <td className="px-2 py-1.5">{a.username}</td>
                <td className="px-2 py-1.5">{a.action}</td>
                <td className="px-4 py-1.5 text-[var(--color-muted)]">{a.detail}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
