"use client";

import Link from "next/link";
import { Clapperboard, VideoOff } from "lucide-react";
import { mediaUrl } from "@/lib/api";
import { useApp } from "@/lib/state";
import type { CameraInfo } from "@/lib/types";

/** Live MJPEG while a camera is being processed; otherwise the last annotated run. */
export function LiveFeed({ camera }: { camera: CameraInfo | undefined }) {
  const { live } = useApp();
  if (!camera) {
    return (
      <div className="grid aspect-video place-items-center rounded-xl border border-dashed border-[var(--color-line-strong)] bg-[var(--color-panel-2)] text-sm text-[var(--color-muted)]">
        <span className="flex items-center gap-2"><VideoOff className="h-4 w-4" /> No cameras configured</span>
      </div>
    );
  }
  const prog = live.progress[camera.id];
  const isLive = !!prog || camera.live;
  const job = camera.latest_job;

  return (
    <div className="relative overflow-hidden rounded-xl bg-slate-900 ring-1 ring-[var(--color-line)]">
      {isLive ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={mediaUrl(`/api/live/${camera.id}.mjpg`)} alt={`${camera.name} live`} className="aspect-video w-full object-contain" />
      ) : job?.annotated_url ? (
        <video key={job.annotated_url} src={mediaUrl(job.annotated_url)} autoPlay muted loop playsInline controls className="aspect-video w-full object-contain" />
      ) : (
        <div className="grid aspect-video place-items-center bg-[var(--color-panel-2)] text-sm text-[var(--color-muted)]">
          <div className="flex flex-col items-center gap-2">
            <VideoOff className="h-6 w-6 text-[var(--color-faint)]" />
            No footage processed for this camera yet
            <Link href="/analyze" className="btn btn-primary mt-1 text-xs"><Clapperboard className="h-3.5 w-3.5" /> Analyze a video</Link>
          </div>
        </div>
      )}
      <div className="absolute left-3 top-3 flex items-center gap-2 text-[11px] font-semibold">
        {isLive ? (
          <span className="flex items-center gap-1.5 rounded-md bg-red-600 px-2 py-1 text-white shadow">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-white" /> LIVE
          </span>
        ) : job?.annotated_url ? (
          <span className="rounded-md bg-white/90 px-2 py-1 text-slate-800 shadow">Replay · run #{job.id}</span>
        ) : null}
        {prog && (
          <span className="num rounded-md bg-white/90 px-2 py-1 text-slate-800 shadow">
            {prog.proc_fps} fps · t={prog.video_t}s{prog.progress != null ? ` · ${Math.round(prog.progress * 100)}%` : ""}
          </span>
        )}
      </div>
    </div>
  );
}
