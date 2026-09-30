"use client";

import dynamic from "next/dynamic";

// Leaflet touches `window` on import, so the map is client-only.
export const ZoneMap = dynamic(() => import("./ZoneMapInner"), {
  ssr: false,
  loading: () => <div className="grid h-[360px] place-items-center text-sm text-[var(--color-muted)]">Loading map…</div>,
});
