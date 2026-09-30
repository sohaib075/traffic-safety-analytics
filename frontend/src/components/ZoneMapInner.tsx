"use client";

import { useEffect } from "react";
import { CircleMarker, MapContainer, Popup, TileLayer, Tooltip, useMap } from "react-leaflet";
import L from "leaflet";
import { LEVEL_COLOR, eventLabel } from "@/lib/format";
import type { ZoneStat } from "@/lib/types";

function Fit({ zones }: { zones: ZoneStat[] }) {
  const map = useMap();
  useEffect(() => {
    const pts = zones.filter((z) => z.lat != null && z.lng != null).map((z) => [z.lat!, z.lng!] as [number, number]);
    if (pts.length === 1) map.setView(pts[0], 18);
    else if (pts.length > 1) map.fitBounds(L.latLngBounds(pts).pad(0.35), { maxZoom: 18 });
  }, [zones, map]);
  return null;
}

export default function ZoneMapInner({
  zones,
  metric = "risk",
  height = 360,
  onSelect,
}: {
  zones: ZoneStat[];
  metric?: "risk" | string; // "risk" or an event type
  height?: number | string;
  onSelect?: (z: ZoneStat) => void;
}) {
  const located = zones.filter((z) => z.lat != null && z.lng != null);
  const valueOf = (z: ZoneStat) => (metric === "risk" ? z.events_total : z.events[metric] ?? 0);
  const maxVal = Math.max(1, ...located.map(valueOf));
  const colorOf = (z: ZoneStat) => {
    if (metric === "risk") return LEVEL_COLOR[z.risk.level];
    const v = valueOf(z) / maxVal;
    return v === 0 ? LEVEL_COLOR.LOW : v < 0.34 ? LEVEL_COLOR.LOW : v < 0.67 ? LEVEL_COLOR.MODERATE : LEVEL_COLOR.HIGH;
  };

  return (
    <MapContainer
      center={located[0] ? [located[0].lat!, located[0].lng!] : [51.5079, -0.0877]}
      zoom={17}
      style={{ height, width: "100%", borderRadius: 8 }}
      scrollWheelZoom
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        className="map-tiles"
      />
      <Fit zones={located} />
      {located.map((z) => {
        const v = valueOf(z);
        const color = colorOf(z);
        return (
          <CircleMarker
            key={`${z.camera_id}:${z.id}`}
            center={[z.lat!, z.lng!]}
            radius={10 + (v / maxVal) * 22}
            pathOptions={{ color, fillColor: color, fillOpacity: 0.35 + (v / maxVal) * 0.35, weight: 2 }}
            eventHandlers={{ click: () => onSelect?.(z) }}
          >
            <Tooltip direction="top" offset={[0, -8]}>
              {z.name} · {v} {metric === "risk" ? "events" : eventLabel(metric, true)}
            </Tooltip>
            <Popup>
              <div style={{ minWidth: 180 }}>
                <div style={{ fontWeight: 600 }}>{z.name}</div>
                <div style={{ fontSize: 11, opacity: 0.7 }}>
                  {z.camera_name} · {z.type}
                </div>
                <div style={{ marginTop: 6, fontSize: 12 }}>
                  Risk: <b style={{ color: LEVEL_COLOR[z.risk.level] }}>{z.risk.level}</b> ({z.risk.score})
                  <br />
                  Vehicles: {z.vehicles} · Pedestrians: {z.pedestrians}
                  {Object.entries(z.events).map(([k, n]) => (
                    <div key={k}>
                      {eventLabel(k, true)}: {n}
                    </div>
                  ))}
                </div>
              </div>
            </Popup>
          </CircleMarker>
        );
      })}
    </MapContainer>
  );
}
