# RoadGuard AI

**See the road. Understand the risk. Investigate every incident.**

RoadGuard AI turns traffic-camera video into structured road-safety intelligence:
YOLO detection → ByteTrack multi-object tracking → trajectory analysis → rule-based event
detection → evidence capture → risk analytics → command dashboard, investigator, AI analyst and
PDF reports.

```
Video ─► YOLO ─► ByteTrack ─► Trajectories ─► Rule engine ─► Incidents + evidence (SQLite)
                                   │               │                     │
                                   ▼               ▼                     ▼
                              counts/zones    near-miss, ped       FastAPI (REST + WS + MJPEG)
                                              conflict, red-light,        │
                                              wrong-way, stopping,        ▼
                                              congestion, helmet    Next.js dashboard
```

All detected events are **potential** indicators for human review, not confirmed violations or
accidents. The dashboard lets operators confirm or dismiss each one.

---

## Quick start (Windows, CPU)

Requirements: Python 3.11, Node 20+. No GPU needed (runs about 10 fps at 768×432 on CPU).

```bash
# backend
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest -q tests          # 22 rule-engine / parser tests
.venv\Scripts\python -m uvicorn roadguard.api:app --port 8010

# frontend (second terminal)
cd frontend
npm install
npm run dev                                       # http://localhost:3000
```

### Accounts

**Login is off by default.** The app opens straight to the dashboard with full access
("Local mode · no login" at the bottom of the sidebar). To turn on accounts and roles, start the
API with `ROADGUARD_AUTH=1`. The rest of this section applies only then.

There are no default passwords. On a fresh database, opening the dashboard shows **first-run
setup**, where you create the first administrator. The admin then manages everyone else under
**Users**:

- **Add a user.** Choose a role (Administrator, Traffic operator or Analyst). A one-time temporary
  password is shown once. The user must replace it at first sign-in, and nothing else in the app
  is reachable until they do.
- **Change role, disable/enable, reset password, delete.** Changes take effect immediately.
  Disabling or resetting ends that user's open sessions.
- **Safety rules.** You can't change your own role, disable yourself or delete yourself, and the
  last active administrator can't be removed.
- **Account page** (click your name at the bottom of the sidebar). Edit your name, change your
  password (with strength check), or sign out of all devices.
- **Security.** PBKDF2 password hashes. Password policy: 10+ characters, 3 of 4 character
  classes, must not contain the username. Sign-in locks for 5 minutes after 5 failed attempts.
  Every account action goes to the audit log.

Locked out? Run these on the server (from `backend/`):

```bash
.venv\Scripts\python -m roadguard.cli users
.venv\Scripts\python -m roadguard.cli reset-password --username <name>
.venv\Scripts\python -m roadguard.cli create-admin --username <name>
```

`config/users.example.yaml` lists the old development accounts. Existing databases that still
use those published passwords are forced to change them at next sign-in. Setting
`ROADGUARD_SEED_USERS=1` recreates them for local development, also with a forced change.

Process a video, either from **Admin → Process video** (upload, a server path such as
`data/samples/car-detection.mp4`, or an `rtsp://` URL), or from the CLI:

```bash
cd backend
.venv\Scripts\python -m roadguard.cli process --camera demo_lot_a --video data/samples/person-bicycle-car-detection.mp4 --start 2026-09-29T17:40:00
.venv\Scripts\python -m roadguard.cli report --date 2026-09-29 --out report.pdf
```

### Analyze any video (no setup)

Open **Analyze video** in the sidebar, drop in any traffic video (MP4, MOV, AVI, MKV, WebM…),
choose **Fast** or **Accurate**, and press *Analyze*. You get upload progress, a live preview
with time remaining, and then a results page with road-user counts, safety events, the
annotated video, and every incident with its evidence clip. This uses the generic
`config/cameras/uploads.yaml` profile: the whole frame is one zone, and the metric scale is
estimated from car sizes.

What runs depends on the setup:

- **Always:** detection and tracking of every road user, counts, helmet compliance and congestion.
- **Opt-in (experimental):** near-miss and pedestrian conflicts. On uncalibrated footage these
  over-fire. On a side-on 40 s street clip they raised about 100 false alarms, so they are off
  unless you tick the box.
- **Needs a camera config drawn for that site (Admin):** red-light (stop line + signal),
  wrong-way (lane directions) and no-stopping (zones).

API: `POST /api/analyze` (multipart `file`, `quality=fast|accurate`, `conflicts=true|false`).

`--start` sets the wall-clock time of the first frame, so recorded footage lands on the right
day and hour in analytics. Tick **Pace playback to real time** in Admin to simulate a live
camera: the Command page then shows the live MJPEG feed and pushes incidents over WebSocket.

### Sample footage

`backend/data/samples/` holds two clips from
[intel-iot-devkit/sample-videos](https://github.com/intel-iot-devkit/sample-videos) (CC BY 4.0).
They are overhead **parking-lot** scenes. They're good for exercising the pipeline, but they are
not intersection footage. The demo configs use a *virtual timed signal* to demonstrate red-light
logic. For a convincing road-safety demo, add a real intersection video (legally usable) and a
camera config drawn for it.

---

## Features

| Area | What is implemented |
|---|---|
| Detection | YOLOv8n (COCO): person, bicycle, car, motorcycle, bus, truck. Set `ROADGUARD_MODEL` to change the model |
| Tracking | ByteTrack via Ultralytics; per-track trajectories, ground-plane velocity by least-squares fit |
| Counting | Unique road users per class per minute; directional counting lines; riders aren't counted as pedestrians |
| Near-miss | Pairwise vehicle conflict: time until separation < combined footprint + margin, given closing speed. Needs confirmation over consecutive frames, with a per-pair cooldown |
| Pedestrian conflict | The same kinematics for vehicle ↔ pedestrian; can be restricted to crosswalk zones |
| Red-light | Stop-line crossing in the configured direction while the signal is red. Signal state comes from a lamp ROI colour classifier, a timed schedule, or a fixed state |
| Wrong-way | Motion against a lane's configured direction, confirmed over several windows |
| Illegal stopping | Stationary vehicle in a `no_stopping` zone beyond a dwell threshold |
| Congestion | Sustained high occupancy and low average speed per zone |
| Helmet | Pluggable. Needs a custom YOLO model with `helmet`/`no_helmet` classes (`rules.helmet.model`). COCO has no helmet class, so it's **off by default** |
| Evidence | For every event: an annotated still and an H.264 clip with 3 s before and 3 s after (bundled ffmpeg), plus the full annotated run video |
| Privacy | Head-region blur on all people in evidence and stream; optional licence-plate model for plate blur |
| Risk engine | Transparent weighted score per 1,000 vehicles (`config/risk.yaml`), with a per-type breakdown shown in the UI |
| Investigator | Filters (type, severity, status, camera, zone, vehicle class, hour window) plus natural-language search ("serious events between 5 PM and 8 PM"); clip playback, measurements, journey reconstruction overlay, confirm/dismiss with notes |
| Map | Leaflet/OSM zone heatmap, by overall risk or by event type |
| Analytics | Volume by class/time, events over time, motorcycle ratio, helmet compliance, zone occupancy/speed, hour-of-day forecast baseline |
| AI Analyst | Tool-calling over the structured DB (summary, zone ranking, incident search, hourly traffic, forecast). Uses Ollama (`OLLAMA_URL`, `OLLAMA_MODEL`) if it's running, otherwise a deterministic rule-based mode. Answers cite incident evidence |
| Reports | Daily PDF: KPIs, risk, hourly chart, zone ranking, incident log, key evidence stills |
| Security | PBKDF2 passwords, HMAC bearer tokens, roles (admin / operator / analyst), evidence-clip access limited to operator and admin, audit log |

### Roles

| | admin | operator | analyst |
|---|:-:|:-:|:-:|
| Dashboards, analytics, map, AI analyst | ✓ | ✓ | ✓ |
| Reports | ✓ | ✓ | ✓ |
| Evidence clips, journeys, incident review | ✓ | ✓ | |
| Submit/stop processing jobs | ✓ | ✓ | |
| Edit camera config, manage users, audit log | ✓ | | |

---

## Configuring a camera

Each camera is a YAML file in `backend/config/cameras/`. All geometry uses **normalized**
coordinates (0–1 of frame width and height). Admin → *Camera scene configuration* overlays the
config on a reference frame and lets an admin edit it.

```yaml
id: junction_b
name: "Intersection B"
location: {lat: 51.50, lng: -0.08}
calibration:                     # homography → metric speeds/distances (recommended)
  image_points: [[0.1,0.9],[0.9,0.9],[0.7,0.4],[0.3,0.4]]
  world_points: [[0,0],[14,0],[14,40],[0,40]]      # metres
zones:    [{id: box, name: "Junction box", type: intersection, polygon: [...], location: {...}}]
lanes:    [{id: nb, name: "Northbound", polygon: [...], direction: [0,-1], zone_id: box}]
signals:  [{id: s1, mode: roi, roi: [0.82,0.05,0.86,0.15]}]   # or schedule / always_red
stop_lines: [{id: sl1, line: [[0.2,0.7],[0.6,0.7]], crossing_direction: [0,-1], signal_id: s1}]
counting_lines: [{id: c1, line: [[0.1,0.8],[0.9,0.8]]}]
rules:
  near_miss:   {ttc_threshold_s: 1.5, min_closing_mps: 2.0, zones: [box]}
  ped_conflict:{zones: [crosswalk_n]}
  helmet:      {enabled: true, model: models/helmet.pt}
```

Without a homography the scene uses a uniform `approx_scene_width_m` scale. Speeds and TTC are
then rough, and the UI flags this on each incident.

---

## Training the helmet model

COCO has no helmet class, so helmet compliance needs a custom model. RoadGuard uses a **YOLO11
classifier on motorcycle crops**. For each tracked motorcycle it crops the bike plus any
overlapping riders, classifies the crop as `helmet` (all riders helmeted) or `no_helmet` (at
least one rider without), and votes across the track.

- **Data:** [HELMET dataset](https://osf.io/4pwj8/) (Lin & Siebert, IEEE Access 2020), CC BY 4.0.
  It has 910 roadside clips from Myanmar and 10,006 tracked motorcycles with per-rider helmet
  labels. The official per-clip split is used, so no clip leaks between train/val/test.
- **Notebook:** open [`backend/training/train_helmet_colab.ipynb`](backend/training/train_helmet_colab.ipynb)
  in Colab or Kaggle with a GPU and run all cells. It streams the ~28 GB of images one part at a
  time, extracts crops with `prepare_helmet_crops.py`, trains, reports crop- and track-level test
  metrics, and downloads `helmet_cls.pt` plus a metrics JSON.
- **Install:** put `helmet_cls.pt` in `backend/models/` and enable it per camera:

```yaml
rules:
  helmet: {enabled: true, model: models/helmet_cls.pt, imgsz: 192, min_conf: 0.6, min_votes: 3}
```

**Local CPU training** (resumable; re-run the same command after any interruption):

```bash
cd backend/training
../.venv/Scripts/python fetch_helmet_subset.py --annotations ../data/datasets/helmet_osf/annotation --split ../data/datasets/helmet_osf/data_split.csv --out ../data/datasets/helmet_cls --budget 2200
../.venv/Scripts/python train_helmet.py      # --fresh to restart, --workers/--threads to tune
```

`fetch_helmet_subset.py` pulls only the frames it needs from the remote zips (HTTP range
requests). 2,200 frames (~700 MB) give 10,154 crops covering 7,625 of 10,006 motorcycles.

**Current model** (`models/helmet_cls.pt`, YOLO11n-cls, 224 px, 25 epochs on CPU):

| Held-out test clips | Accuracy | No-helmet precision | No-helmet recall |
|---|---|---|---|
| Per crop (1,922) | 87.2% | 84.6% | 78.9% |
| Per motorcycle track (1,422) | 88.5% | 86.7% | 79.5% |
| **Full pipeline** on the Mandalay demo (4 test clips, 131 labelled motorcycles) | 83.1% per track | 85.7% per track, 73% of incidents | 52% |

The full pipeline is what an operator sees. It scores lower because detection and tracking
lose motorcycles in dense 10 fps traffic: 78 of 131 get a usable track. Run the evaluation with
`training/eval_helmet_demo.py` and `training/diagnose_tracking.py`. Lessons baked into the code:

- Crops are **letterboxed to square**. YOLO-cls centre-crops, which cut riders' heads off tall crops.
- Decisions use the **mean P(no_helmet) over a track**, not hard votes with an abstain threshold
  (that biased tracks towards "helmet"). Early incidents need a higher mean (`early_threshold`).
- People and vehicles are tracked by **separate ByteTrack instances**
  (`pipeline/tracking.py`). One class-agnostic tracker let riders steal motorcycle IDs.
- Detector and tracker are set **per camera** (`model:`, `tracker:`). The Mandalay demo uses
  `yolo11s.pt` with `config/trackers/roadguard_bytetrack.yaml`.
- Head blurring is **off** for helmet cameras, because it hides what the reviewer must verify.
  Evidence access is role-restricted instead.

Demo video: `data/samples/helmet_demo_mandalay.mp4` (HELMET test split, CC BY 4.0), camera
`demo_mandalay`. Build other demos with `training/make_helmet_demo.py <test clips>`.

After editing `prepare_helmet_crops.py`, regenerate the notebook with
`python backend/training/build_notebook.py`, which embeds the script.

Why not a head detector? The public head-level sets checked (Kaggle `andrewmvd/helmet-detection`)
are mostly bicycle helmets, with many unlabelled heads. `pkdarabi/helmet` labels the whole
rider+bike, so it can't be merged with head-level labels. HELMET matches the traffic-camera view
and the tracker's motorcycle boxes.

## Project layout

```
backend/
  roadguard/
    pipeline/        geometry, tracks, rules, signals, helmet, annotate, evidence, runner
    api.py           FastAPI app (REST, WebSocket /ws, MJPEG /api/live/<cam>.mjpg, /evidence)
    analytics.py     summary / time series / zones / risk / forecast queries
    analyst.py       AI analyst (Ollama tool-calling + rule-based fallback)
    reports.py       daily PDF
    auth.py accounts_api.py db.py jobs.py nlq.py cli.py camera_config.py settings.py
  config/            cameras/*.yaml, trackers/*.yaml, risk.yaml, users.example.yaml
  data/              SQLite DB, evidence, uploads, samples (git-ignored except samples)
  tests/
frontend/            Next.js 16 + Tailwind 4 + Recharts + react-leaflet
```

## Honest limitations / next steps

- Near-miss and conflict thresholds need tuning per site, and uncalibrated cameras give only
  approximate metric values. Use a homography.
- Helmet detection needs a trained model (for example from a public helmet dataset). The hook
  and statistics are in place.
- Forecasting is an hour-of-day statistical baseline. Add a tree-based model once there are
  weeks of history.
- SQLite plus in-process job threads suit a single machine. For multi-camera production, move to
  PostgreSQL (`ROADGUARD_DB`; note the SQLite `strftime` in the hour filter), a job queue and
  Redis pub/sub for the live hub.
- Cross-camera re-identification, the smart parking module and a mobile app are not implemented
  (spec §26 advanced features).
