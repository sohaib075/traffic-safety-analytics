"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { CheckCircle2, Clapperboard, FileVideo, Gauge, Info, Loader2, Rocket, Square, Upload, XCircle } from "lucide-react";
import { API_BASE, api, getToken, mediaUrl, qs } from "@/lib/api";
import { CLASS_COLOR, EVENT_META, fmtDate, fmtTime, nf } from "@/lib/format";
import { useApp, useFetch } from "@/lib/state";
import type { Incident, Job } from "@/lib/types";
import { useToast } from "@/components/forms";
import { Empty, EventBadge, Panel, SeverityBadge, StatusBadge } from "@/components/ui";

type Quality = "fast" | "accurate";
const MODES: Record<Quality, { title: string; icon: typeof Rocket; desc: string; procFps: number; stride: (fps: number) => number }> = {
  fast: { title: "Fast", icon: Rocket, desc: "Small detector, samples frames. Good for long videos and quick looks.", procFps: 8, stride: (f) => (f >= 40 ? 3 : f >= 20 ? 2 : 1) },
  accurate: { title: "Accurate", icon: Gauge, desc: "Larger detector, every frame (or every 2nd at high fps). Best results.", procFps: 2.8, stride: (f) => (f >= 40 ? 2 : 1) },
};
const ACCEPT = ".mp4,.avi,.mov,.mkv,.webm,.m4v,.mpg,.mpeg,.wmv,.ts,video/*";
const CAMERA = "uploads";

function fmtDuration(s: number) {
  if (!isFinite(s) || s <= 0) return "—";
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return m ? `${m} min ${sec.toString().padStart(2, "0")} s` : `${sec} s`;
}
const fmtSize = (b: number) => (b > 1e9 ? `${(b / 1e9).toFixed(2)} GB` : `${(b / 1e6).toFixed(1)} MB`);

/** multipart upload with progress (fetch() can't report upload progress) */
function uploadWithProgress(fd: FormData, onProgress: (p: number) => void, signal: AbortSignal) {
  return new Promise<{ job_id: number }>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/api/analyze`);
    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      let body: any = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* ignore */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else reject(new Error(body?.detail ?? `Upload failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error("Network error — is the API running?"));
    signal.addEventListener("abort", () => {
      xhr.abort();
      reject(new Error("Upload cancelled"));
    });
    xhr.send(fd);
  });
}

function Analyzer() {
  const params = useSearchParams();
  const router = useRouter();
  const jobParam = params.get("job");
  const jobId = jobParam ? Number(jobParam) : null;
  return jobId ? <JobView jobId={jobId} onNew={() => router.push("/analyze")} /> : <UploadView onStarted={(id) => router.push(`/analyze?job=${id}`)} />;
}

/* ------------------------------------------------------------------ upload */
function UploadView({ onStarted }: { onStarted: (jobId: number) => void }) {
  const { can } = useApp();
  const [file, setFile] = useState<File | null>(null);
  const [meta, setMeta] = useState<{ duration: number; width: number; height: number; thumb: string | null } | null>(null);
  const [quality, setQuality] = useState<Quality>("accurate");
  const [conflicts, setConflicts] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const pick = useCallback((f: File | undefined | null) => {
    setError(null);
    setMeta(null);
    if (!f) return;
    setFile(f);
    // Read duration/resolution + a thumbnail in the browser, before uploading anything.
    const url = URL.createObjectURL(f);
    const v = document.createElement("video");
    v.preload = "metadata";
    v.muted = true;
    v.src = url;
    v.onloadedmetadata = () => {
      v.currentTime = Math.min(1, (v.duration || 2) / 2);
    };
    v.onseeked = () => {
      let thumb: string | null = null;
      try {
        const c = document.createElement("canvas");
        c.width = 320;
        c.height = Math.round((320 * v.videoHeight) / Math.max(1, v.videoWidth));
        c.getContext("2d")!.drawImage(v, 0, 0, c.width, c.height);
        thumb = c.toDataURL("image/jpeg", 0.7);
      } catch {
        /* codec not previewable in browser — fine, the server still decodes it */
      }
      setMeta({ duration: v.duration, width: v.videoWidth, height: v.videoHeight, thumb });
      URL.revokeObjectURL(url);
    };
    v.onerror = () => {
      setMeta({ duration: NaN, width: 0, height: 0, thumb: null });
      URL.revokeObjectURL(url);
    };
  }, []);

  const start = async () => {
    if (!file) return;
    setError(null);
    setProgress(0);
    const fd = new FormData();
    fd.set("file", file);
    fd.set("quality", quality);
    fd.set("conflicts", String(conflicts));
    abortRef.current = new AbortController();
    try {
      const r = await uploadWithProgress(fd, setProgress, abortRef.current.signal);
      onStarted(r.job_id);
    } catch (e) {
      setError((e as Error).message);
      setProgress(null);
    }
  };

  // Rough time estimate: frames to process / typical processing speed on this machine.
  const estimate = meta && isFinite(meta.duration) ? (meta.duration * 25) / MODES[quality].stride(25) / MODES[quality].procFps : null;

  if (!can("process")) return <Empty>Your role can view results but not analyse new videos.</Empty>;

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div>
        <h1 className="flex items-center gap-2 text-xl font-semibold">
          <Clapperboard className="h-5 w-5 text-[var(--color-accent)]" /> Analyze a video
        </h1>
        <p className="mt-1 text-sm text-[var(--color-muted)]">
          Upload any traffic video — RoadGuard detects and tracks every road user, counts traffic and flags potential safety
          events with evidence clips. No camera setup needed.
        </p>
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          pick(e.dataTransfer.files?.[0]);
        }}
        onClick={() => progress === null && inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
        className={`panel cursor-pointer border-2 border-dashed p-6 transition-colors ${
          dragging ? "border-[var(--color-accent)] bg-[var(--color-accent)]/5" : "hover:border-[#33445c]"
        }`}
      >
        <input ref={inputRef} type="file" accept={ACCEPT} className="hidden" onChange={(e) => pick(e.target.files?.[0])} />
        {file ? (
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
            <div className="grid aspect-video w-full shrink-0 place-items-center overflow-hidden rounded-md bg-black sm:w-48">
              {meta?.thumb ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={meta.thumb} alt="" className="h-full w-full object-cover" />
              ) : (
                <FileVideo className="h-8 w-8 text-[var(--color-faint)]" />
              )}
            </div>
            <div className="min-w-0 text-sm">
              <div className="truncate font-medium">{file.name}</div>
              <div className="mt-1 text-[var(--color-muted)]">
                {fmtSize(file.size)}
                {meta && isFinite(meta.duration) && ` · ${fmtDuration(meta.duration)}`}
                {meta && meta.width > 0 && ` · ${meta.width}×${meta.height}`}
              </div>
              <div className="mt-2 text-xs text-[var(--color-accent)]">Click or drop another file to replace</div>
            </div>
          </div>
        ) : (
          <div className="py-8 text-center">
            <Upload className="mx-auto h-8 w-8 text-[var(--color-accent)]" />
            <div className="mt-3 font-medium">Drop a video here, or click to choose</div>
            <div className="mt-1 text-xs text-[var(--color-muted)]">MP4, MOV, AVI, MKV, WebM… any resolution</div>
          </div>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {(Object.keys(MODES) as Quality[]).map((q) => {
          const m = MODES[q];
          const Icon = m.icon;
          return (
            <button
              key={q}
              type="button"
              onClick={() => setQuality(q)}
              className={`panel p-4 text-left transition-colors ${quality === q ? "border-[var(--color-accent)] bg-[var(--color-accent)]/10" : "hover:border-[#33445c]"}`}
              aria-pressed={quality === q}
            >
              <div className="flex items-center gap-2 font-medium">
                <Icon className="h-4 w-4 text-[var(--color-accent)]" /> {m.title}
              </div>
              <div className="mt-1 text-xs text-[var(--color-muted)]">{m.desc}</div>
            </button>
          );
        })}
      </div>

      <label className="panel flex cursor-pointer items-start gap-3 p-4 text-sm">
        <input type="checkbox" className="mt-1" checked={conflicts} onChange={(e) => setConflicts(e.target.checked)} />
        <span>
          <span className="font-medium">Also detect potential near-misses &amp; pedestrian conflicts</span>
          <span className="ml-2 rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-amber-300">Experimental</span>
          <span className="mt-1 block text-xs text-[var(--color-muted)]">
            Without a calibrated camera, distances are guessed from the picture, so busy or side-on footage produces many
            false alarms. Best for overhead or elevated views; for reliable results calibrate a dedicated camera in Admin.
          </span>
        </span>
      </label>

      {progress !== null ? (
        <div className="panel space-y-2 p-4">
          <div className="flex justify-between text-sm">
            <span>Uploading…</span>
            <span className="num">{Math.round(progress * 100)}%</span>
          </div>
          <div className="h-2 rounded-full bg-[var(--color-panel-2)]">
            <div className="h-2 rounded-full bg-[var(--color-accent)] transition-all" style={{ width: `${progress * 100}%` }} />
          </div>
          <button className="btn text-xs" onClick={() => abortRef.current?.abort()}>Cancel</button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-3">
          <button className="btn btn-primary px-5 py-2" disabled={!file} onClick={start}>
            <Clapperboard className="h-4 w-4" /> Analyze video
          </button>
          {estimate && <span className="text-xs text-[var(--color-muted)]">Estimated processing time on this machine: ~{fmtDuration(estimate)}</span>}
        </div>
      )}
      {error && (
        <div role="alert" className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          <XCircle className="mt-0.5 h-4 w-4 shrink-0" /> {error}
        </div>
      )}

      <div className="flex items-start gap-2 rounded-md bg-[var(--color-panel-2)] px-3 py-2.5 text-xs text-[var(--color-muted)]">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>
          Always runs: detection &amp; tracking of every road user, traffic counts by type, helmet compliance for motorcycle
          riders, congestion, annotated video. <b className="text-[var(--color-ink)]">Red-light, wrong-way and no-stopping</b>{" "}
          checks need a stop line, lane directions or zones drawn for that specific camera — set that up under Admin → Camera
          configuration.
        </span>
      </div>

      <RecentAnalyses />
    </div>
  );
}

function RecentAnalyses() {
  const { live } = useApp();
  const { data } = useFetch<Job[]>(`/api/jobs${qs({ camera: CAMERA, limit: 10 })}`, [live.tick]);
  if (!data?.length) return null;
  return (
    <Panel title="Recent analyses" bodyClass="p-0">
      <ul className="divide-y divide-[var(--color-line)] text-sm">
        {data.map((j) => {
          const ev = (j.summary as any)?.events as Record<string, number> | undefined;
          const total = ev ? Object.values(ev).reduce((a, b) => a + b, 0) : null;
          return (
            <li key={j.id}>
              <Link href={`/analyze?job=${j.id}`} className="flex items-center gap-3 px-4 py-2.5 hover:bg-[var(--color-panel-2)]">
                <FileVideo className="h-4 w-4 shrink-0 text-[var(--color-faint)]" />
                <span className="min-w-0 flex-1 truncate">{j.source}</span>
                <span className="hidden text-xs text-[var(--color-muted)] sm:inline">{fmtDate(j.created_at)} {fmtTime(j.created_at, false)}</span>
                {total !== null && <span className="num text-xs text-[var(--color-muted)]">{total} events</span>}
                <StatusBadge s={j.status} />
              </Link>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}

/* ------------------------------------------------------------------ processing + results */
function JobView({ jobId, onNew }: { jobId: number; onNew: () => void }) {
  const { live, can } = useApp();
  const toast = useToast();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Poll the job while it runs (WebSocket progress fills in between polls).
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try {
        const j = await api<Job>(`/api/jobs/${jobId}`);
        if (!alive) return;
        setJob(j);
        if (j.status === "queued" || j.status === "running") timer = setTimeout(load, 2000);
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    };
    load();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [jobId, live.tick]);

  if (error) return <Empty>{error}</Empty>;
  if (!job) return <div className="grid place-items-center py-20 text-sm text-[var(--color-muted)]"><Loader2 className="h-5 w-5 animate-spin" /></div>;

  const running = job.status === "queued" || job.status === "running";
  const lp = live.progress[job.camera_id]?.job_id === job.id ? live.progress[job.camera_id] : job.live;
  const progress = lp?.progress ?? job.progress ?? 0;
  const procFps = lp?.proc_fps ?? job.proc_fps ?? 0;
  const stride = (job.summary as any)?.frame_stride ?? 1;
  const remainingFrames = job.total_frames ? (job.total_frames * (1 - progress)) / stride : null;
  const eta = remainingFrames && procFps ? remainingFrames / procFps : null;

  const cancel = async () => {
    try {
      await api(`/api/jobs/${job.id}/cancel`, { method: "POST" });
      toast("Stopping analysis…");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-xs text-[var(--color-muted)]">Analysis #{job.id}</div>
          <h1 className="truncate text-xl font-semibold">{job.source}</h1>
        </div>
        <StatusBadge s={job.status} />
        {running && can("process") && (
          <button className="btn" onClick={cancel}>
            <Square className="h-3.5 w-3.5" /> Stop
          </button>
        )}
        <button className="btn btn-primary" onClick={onNew}>
          <Upload className="h-4 w-4" /> Analyze another video
        </button>
      </div>

      {running ? (
        <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
          <Panel title="Live processing" bodyClass="p-3">
            <div className="overflow-hidden rounded-md bg-black">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={mediaUrl(`/api/live/${job.camera_id}.mjpg`)} alt="Live annotated frames" className="aspect-video w-full object-contain" />
            </div>
          </Panel>
          <Panel title="Progress">
            <div className="space-y-4">
              <div>
                <div className="mb-1.5 flex justify-between text-sm">
                  <span className="flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin text-[var(--color-accent)]" /> {job.status === "queued" ? "Starting…" : "Analyzing frames"}</span>
                  <span className="num">{Math.round(progress * 100)}%</span>
                </div>
                <div className="h-2.5 rounded-full bg-[var(--color-panel-2)]">
                  <div className="h-2.5 rounded-full bg-[var(--color-accent)] transition-all" style={{ width: `${Math.max(2, progress * 100)}%` }} />
                </div>
              </div>
              <dl className="grid grid-cols-2 gap-3 text-sm">
                <Stat label="Time remaining" value={eta ? `~${fmtDuration(eta)}` : "estimating…"} />
                <Stat label="Speed" value={procFps ? `${procFps.toFixed(1)} frames/s` : "—"} />
                <Stat label="Video position" value={lp ? `${lp.video_t.toFixed(0)} s` : "—"} />
                <Stat label="Elapsed" value={fmtDuration((Date.now() - new Date(job.created_at).getTime()) / 1000)} />
              </dl>
              {lp && Object.keys(lp.live.objects).length > 0 && (
                <div>
                  <div className="mb-1.5 text-xs text-[var(--color-muted)]">In view now</div>
                  <div className="flex flex-wrap gap-2 text-xs">
                    {Object.entries(lp.live.objects).map(([k, v]) => (
                      <span key={k} className="rounded-full bg-[var(--color-panel-2)] px-2.5 py-1">
                        <span style={{ color: CLASS_COLOR[k] ?? "#8b98ab" }}>●</span> {k} {v}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              <p className="text-xs text-[var(--color-faint)]">You can leave this page — the analysis keeps running and appears under Recent analyses.</p>
            </div>
          </Panel>
        </div>
      ) : job.status === "failed" ? (
        <div className="flex items-start gap-2 rounded-md border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
          <XCircle className="mt-0.5 h-4 w-4 shrink-0" /> Analysis failed: {job.error}
        </div>
      ) : (
        <Results job={job} />
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-md bg-[var(--color-panel-2)] px-3 py-2">
      <dt className="text-xs text-[var(--color-muted)]">{label}</dt>
      <dd className="num mt-0.5 font-medium">{value}</dd>
    </div>
  );
}

function Results({ job }: { job: Job }) {
  const s = job.summary as any;
  const classes: Record<string, number> = s?.classes ?? {};
  const events: Record<string, number> = s?.events ?? {};
  const vehicles = Object.entries(classes).filter(([k]) => k !== "pedestrian").reduce((a, [, v]) => a + v, 0);
  const totalEvents = Object.values(events).reduce((a, b) => a + b, 0);
  const { data: inc } = useFetch<{ total: number; items: Incident[] }>(`/api/incidents${qs({ job: job.id, limit: 60, order: "asc" })}`);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-sm text-emerald-300">
        <CheckCircle2 className="h-4 w-4" /> {job.status === "cancelled" ? "Stopped early — results cover the part that was processed." : "Analysis complete."}
        <span className="text-[var(--color-muted)]">
          {s?.video_seconds ? `${fmtDuration(s.video_seconds)} of video` : ""}
          {s?.processing_seconds ? ` in ${fmtDuration(s.processing_seconds)}` : ""}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi label="Vehicles" value={nf.format(vehicles)} />
        <Kpi label="Pedestrians" value={nf.format(classes.pedestrian ?? 0)} />
        <Kpi label="Safety events" value={totalEvents} accent={totalEvents ? "#f97316" : undefined} />
        <Kpi label="Helmet checks" value={s?.helmet?.enabled ? `${s.helmet.violations} / ${s.helmet.checked}` : "off"} sub={s?.helmet?.enabled ? "potential violations / motorcycles judged" : undefined} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        <Panel title="Annotated video" bodyClass="p-3">
          {job.annotated_url ? (
            <video src={mediaUrl(job.annotated_url)} controls playsInline className="aspect-video w-full rounded-md bg-black" />
          ) : (
            <Empty>No annotated video was saved.</Empty>
          )}
          {s?.scale_note && <p className="mt-2 text-xs text-[var(--color-faint)]">Distances are approximate ({s.scale_note}).</p>}
        </Panel>
        <div className="space-y-4">
          <Panel title="Road users">
            {Object.keys(classes).length ? (
              <div className="space-y-2">
                {Object.entries(classes).sort((a, b) => b[1] - a[1]).map(([k, v]) => {
                  const max = Math.max(...Object.values(classes));
                  return (
                    <div key={k} className="grid grid-cols-[90px_1fr_40px] items-center gap-2 text-sm">
                      <span className="capitalize text-[var(--color-muted)]">{k}</span>
                      <div className="h-2 rounded-full bg-[var(--color-panel-2)]"><div className="h-2 rounded-full" style={{ width: `${(v / max) * 100}%`, background: CLASS_COLOR[k] ?? "#8b98ab" }} /></div>
                      <span className="num text-right">{v}</span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <Empty>No road users detected.</Empty>
            )}
          </Panel>
          <Panel title="Events by type">
            {s?.rules_enabled && (
              <div className="mb-3 flex flex-wrap gap-1.5">
                {Object.entries(s.rules_enabled as Record<string, boolean>).map(([k, on]) => (
                  <span
                    key={k}
                    title={on ? "This check ran" : "Not run for this video"}
                    className={`rounded-full px-2 py-0.5 text-[11px] ${on ? "bg-emerald-500/10 text-emerald-300" : "bg-[var(--color-panel-2)] text-[var(--color-faint)] line-through"}`}
                  >
                    {EVENT_META[k]?.short ?? k}
                  </span>
                ))}
              </div>
            )}
            {totalEvents ? (
              <div className="space-y-1.5 text-sm">
                {Object.entries(events).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between">
                    <EventBadge t={k} short={false} />
                    <span className="num">{v}</span>
                  </div>
                ))}
              </div>
            ) : (
              <Empty>No potential safety events were detected.</Empty>
            )}
          </Panel>
        </div>
      </div>

      <Panel
        title={`Incidents${inc ? ` (${inc.total})` : ""}`}
        right={inc && inc.total > 0 ? <Link href="/incidents" className="text-xs text-[var(--color-accent)]">Open Investigator →</Link> : null}
      >
        {inc && inc.items.length === 0 && <Empty>Nothing to review.</Empty>}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {inc?.items.map((i) => (
            <Link key={i.id} href={`/incidents?id=${i.id}`} className="panel block overflow-hidden hover:border-[var(--color-accent)]">
              {i.snapshot_url && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={mediaUrl(i.snapshot_url)} alt="" className="aspect-video w-full object-cover" loading="lazy" />
              )}
              <div className="flex items-center justify-between gap-2 px-3 py-2 text-xs">
                <EventBadge t={i.type} />
                <span className="num text-[var(--color-muted)]">at {i.video_t.toFixed(1)} s</span>
                <SeverityBadge s={i.severity} />
              </div>
            </Link>
          ))}
        </div>
      </Panel>
    </div>
  );
}

function Kpi({ label, value, sub, accent }: { label: string; value: React.ReactNode; sub?: string; accent?: string }) {
  return (
    <div className="panel px-4 py-3">
      <div className="panel-title">{label}</div>
      <div className="num mt-1 text-2xl font-semibold" style={accent ? { color: accent } : undefined}>{value}</div>
      {sub && <div className="text-[11px] text-[var(--color-faint)]">{sub}</div>}
    </div>
  );
}

export default function Page() {
  return (
    <Suspense>
      <Analyzer />
    </Suspense>
  );
}
