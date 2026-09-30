"use client";

import { mediaUrl } from "@/lib/api";
import { useApp } from "@/lib/state";
import type { CameraInfo } from "@/lib/types";

/** Live MJPEG while a camera is being processed; otherwise the last annotated run. */
export function LiveFeed({ camera }: { camera: CameraInfo | undefined }) {
  const { live } = useApp();
  if (!camera) {
    return <div className="grid aspect-video place-items-center rounded-md bg-black/40 text-sm text-[var(--color-muted)]">No cameras configured</div>;
  }
  const prog = live.progress[camera.id];
  const isLive = !!prog || camera.live;
  const job = camera.latest_job;

  return (
    <div className="relative overflow-hidden rounded-md bg-black">
      {isLive ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={mediaUrl(`/api/live/${camera.id}.mjpg`)} alt={`${camera.name} live`} className="aspect-video w-full object-contain" />
      ) : job?.annotated_url ? (
        <video key={job.annotated_url} src={mediaUrl(job.annotated_url)} autoPlay muted loop playsInline controls className="aspect-video w-full object-contain" />
      ) : (
        <div className="grid aspect-video place-items-center text-sm text-[var(--color-muted)]">
          No footage processed yet — submit a video from Admin.
        </div>
      )}
      <div className="absolute left-2 top-2 flex items-center gap-2 text-[11px]">
        {isLive ? (
          <span className="flex items-center gap-1 rounded bg-red-600 px-1.5 py-0.5 font-semibold">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-white" /> LIVE
          </span>
        ) : job?.annotated_url ? (
          <span className="rounded bg-black/70 px-1.5 py-0.5 text-[var(--color-muted)]">REPLAY · job #{job.id}</span>
        ) : null}
        {prog && (
          <span className="num rounded bg-black/70 px-1.5 py-0.5 text-[var(--color-muted)]">
            {prog.proc_fps} fps · t={prog.video_t}s{prog.progress != null ? ` · ${Math.round(prog.progress * 100)}%` : ""}
          </span>
        )}
      </div>
    </div>
  );
}
