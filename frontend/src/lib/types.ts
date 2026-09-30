export type Severity = "low" | "medium" | "high";
export type Role = "admin" | "operator" | "analyst";

export interface Account {
  id: number;
  username: string;
  full_name: string;
  role: Role;
  role_label: string;
  active: boolean;
  must_change_password: boolean;
  created_at: string | null;
  last_login: string | null;
  password_changed_at: string | null;
}

export interface Me extends Account {
  permissions: string[];
  auth_enabled?: boolean;
}

export interface Incident {
  id: number;
  job_id: number;
  camera_id: string;
  type: string;
  severity: Severity;
  zone_id: string | null;
  zone_name: string | null;
  occurred_at: string;
  video_t: number;
  track_ids: number[];
  classes: string[];
  metrics: Record<string, number | string | boolean>;
  confidence: number;
  description: string;
  snapshot_url: string | null;
  clip_url: string | null;
  clip_ready: boolean;
  status: "new" | "confirmed" | "dismissed";
  notes: string;
  journeys?: Journey[];
  _update?: boolean;
}

export interface Journey {
  job_id: number;
  track_id: number;
  cls: string;
  camera_id: string;
  first_seen: string;
  last_seen: string;
  video_t0: number;
  video_t1: number;
  route: { zone_id: string; name: string }[];
  path: [number, number, number][];
  max_speed_mps: number;
  events: string[];
  helmet: string | null;
}

export interface RiskBreakdown {
  type: string;
  label: string;
  count: number;
  weight: number;
  points: number;
}

export interface Risk {
  score: number;
  level: "LOW" | "MODERATE" | "HIGH" | "CRITICAL";
  weighted_points: number;
  vehicles: number;
  denominator: number;
  breakdown: RiskBreakdown[];
  method: string;
}

export interface Summary {
  range: { start: string; end: string; camera: string | null };
  volume: Record<string, number>;
  vehicles: number;
  pedestrians: number;
  events: Record<string, number>;
  events_by_severity: Record<string, Record<string, number>>;
  total_events: number;
  review_status: Record<string, number>;
  helmet: { motorcycles: number; checked: number; compliant: number; violations: number };
  risk: Risk;
  peak_hour: string | null;
  top_zone: { id: string; name: string; risk: Risk } | null;
}

export interface Bucket {
  start: string;
  vehicles: number;
  pedestrian: number;
  events: number;
  car: number;
  motorcycle: number;
  bus: number;
  truck: number;
  bicycle: number;
  by_type: Record<string, number>;
}

export interface ZoneStat {
  id: string;
  camera_id: string;
  camera_name: string;
  name: string;
  type: string;
  lat: number | null;
  lng: number | null;
  polygon: [number, number][];
  vehicles: number;
  pedestrians: number;
  occupancy_avg: number | null;
  occupancy_max: number | null;
  speed_avg_mps: number | null;
  events: Record<string, number>;
  events_total: number;
  risk: Risk;
}

export interface Job {
  id: number;
  camera_id: string;
  source: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  progress: number;
  video_start: string;
  fps: number | null;
  total_frames: number | null;
  frames_processed: number;
  proc_fps: number | null;
  annotated_url: string | null;
  summary: Record<string, unknown>;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  live: LiveProgress | null;
}

export interface LiveProgress {
  job_id: number;
  camera_id?: string;
  progress: number | null;
  frames_processed: number;
  proc_fps: number;
  video_t: number;
  live: {
    objects: Record<string, number>;
    zones: Record<string, { vehicles: number; people: number; avg_speed_mps: number | null }>;
    signals: Record<string, string>;
  };
}

export interface CameraInfo {
  id: string;
  name: string;
  location: { lat: number; lng: number } | null;
  zones: { id: string; name: string; type: string }[];
  calibrated: boolean;
  helmet_enabled: boolean;
  live: boolean;
  latest_job: Job | null;
}

export interface Forecast {
  method: string;
  days_of_history: number;
  hours: { hour: number; expected_vehicles: number | null; samples: number }[];
  expected_congestion_window: { start: string; end: string } | null;
}
