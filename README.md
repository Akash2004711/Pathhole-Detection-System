# AI-Powered Pothole Detection and Reporting System

An end-to-end road-safety application that detects potholes from images,
videos and live camera captures using a YOLO model, attaches GPS locations,
stores reports in **Firebase (Firestore)**, notifies authorities by email, and
gives government officials a dashboard to verify, prioritise, assign and track
repairs.

> **Correct technical description:** AI-Powered Pothole Detection and Reporting
> System using Computer Vision, YOLO, FastAPI, Firebase, GPS and Maps.

This repository previously contained only a static detection front-end. The
full stack (FastAPI + YOLO inference + Firebase auth/Firestore/Storage + two
dashboards + email + tests + security rules) has now been implemented around
that front-end.

---

## 1. Problem statement

Road potholes cause accidents and vehicle damage, but citizen reports are
often slow to reach the responsible authority and hard to triage. This system
automates pothole detection with computer vision and structures the
report → verify → assign → repair → confirm workflow so authorities act on
real, GPS-located evidence.

## 2. Objectives

- Detect potholes from **image upload, video upload and camera capture**.
- Attach **GPS coordinates** and a map-based location picker.
- Store reports and media in **Firebase** with proper authentication.
- Provide exactly **two dashboards**: User and Government Authority.
- Support a full **repair lifecycle** with an auditable status history.
- Send **email notifications** on key status changes.

## 3. Architecture

```
Browser (static Frontend: HTML/CSS/JS + Firebase Web SDK)
        │  HTTPS + Firebase ID token (Authorization: Bearer …)
        ▼
FastAPI backend  ──►  YOLO inference service (image / video)
        │                     │
        │                     ▼
        │              annotated image + detections
        ▼
Firebase Admin SDK ──► Cloud Firestore (users, reports, history, teams, logs)
                 └──►  Cloud Storage   (original / annotated / evidence media)
                 └──►  Firebase Auth   (ID-token verification)
        │
        ▼
SMTP email service (best-effort notifications)
```

## 4. Technology stack

| Layer | Choice |
|------|--------|
| AI / CV | Python, Ultralytics YOLO, OpenCV, Pillow, NumPy, PyTorch |
| Backend | FastAPI, Uvicorn, Pydantic v2, pydantic-settings |
| Auth & DB | Firebase Auth, Cloud Firestore, Cloud Storage (Firebase Admin SDK) |
| Frontend | HTML5, CSS3, vanilla JS, Firebase Web SDK (compat), Leaflet (OpenStreetMap) |
| Email | SMTP via `smtplib` (configured by environment) |
| Tests | pytest + FastAPI TestClient |

The existing plain HTML/CSS/JS front-end was **preserved and extended** rather
than replaced.

## 5. Repository structure

```
Pothole Detection System/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI app, CORS, error handling, static mount
│   │   ├── config.py             # Settings from environment (.env)
│   │   ├── auth.py               # ID-token verification + role authorization
│   │   ├── schemas.py            # Pydantic models + status-transition map
│   │   ├── firebase_client.py    # Lazy, safe Firebase Admin init
│   │   ├── detection/
│   │   │   ├── yolo_service.py   # image + video inference (loads model once)
│   │   │   └── file_utils.py     # upload validation + temp-file handling
│   │   ├── routers/
│   │   │   ├── health.py         # /api/health, /api/config
│   │   │   ├── detection.py      # /api/detection/image, /video
│   │   │   ├── reports.py        # user report endpoints
│   │   │   └── authority.py      # government endpoints + teams + evidence
│   │   └── services/
│   │       ├── report_service.py # Firestore CRUD, history, analytics
│   │       ├── storage_service.py# Cloud Storage upload + signed URLs
│   │       └── email_service.py  # SMTP notifications (best-effort)
│   ├── scripts/grant_authority.py# Admin: assign the authority role
│   ├── tests/                    # pytest suite (no credentials required)
│   ├── requirements.txt
│   └── .env.example
├── Frontend/
│   ├── index.html                # Landing + login/register
│   ├── user.html                 # USER DASHBOARD
│   ├── authority.html            # GOVERNMENT AUTHORITY DASHBOARD
│   ├── style.css                 # Shared styles
│   └── js/
│       ├── common.js             # config + apiFetch + helpers
│       ├── auth.js               # Firebase auth + role guard
│       ├── map.js                # Leaflet map + geolocation
│       ├── user-app.js           # User dashboard logic
│       └── authority-app.js      # Authority dashboard logic
├── firebase/
│   ├── firestore.rules
│   ├── storage.rules
│   └── firebase.json
├── .gitignore
└── README.md
```

## 6. AI detection workflow

1. Validate the uploaded file (size, decoded content — never trust the client MIME type).
2. Load the configured YOLO weights **once per process**.
3. Run inference with configured confidence + IoU thresholds.
4. Extract real class labels, confidence scores and bounding boxes.
5. Produce an annotated image and record inference time.
6. Return a consistent `DetectionResult` JSON (no fabricated results).

Video inference samples frames on a configurable stride (`VIDEO_FRAME_SAMPLE_STRIDE`)
with bounded frames/duration. Video counts are **per-frame** detections (they
may repeat the same physical pothole across frames); no cross-frame tracking is
claimed.

> **Honesty guarantee:** if the model weights are missing or fail to load, the
> API returns `503` with an actionable message. It **never** returns mock
> predictions. See [Model weights](#13-model-weights).

## 7. User Dashboard (`user.html`)

- **Overview** — real counts of the signed-in user's reports by status + recent activity.
- **Detect** — image upload, video upload, and **live camera detection**. Opening
  the camera auto-starts real-time inference: frames are sampled about once per
  second, sent to the backend YOLO model, pothole bounding boxes are drawn over
  the live feed, and a HUD shows count / confidence / latency. Detected potholes
  can be **auto-filed as reports** (de-duplicated: only when a new pothole
  appears, with a minimum interval) so both dashboards update live.
- **Submit a report** — GPS fields, "use my location", a draggable map pin, address/description/category; attaches the latest detection automatically.
- **My reports** — search, status filter, list of the user's own reports only.
- **Report details** — media, location, detection summary, status timeline (Submitted → Under Review → Verified → Assigned → In Progress → Resolved, plus Rejected/Duplicate), and official review notes.
- **Nearby** — interactive map of reported potholes with an optional 5 km filter.
- **Profile** — update display name; role is shown but not editable by the user.

## 8. Government Authority Dashboard (`authority.html`)

- **Overview** — real database-backed statistics (new, pending verification, high priority, awaiting assignment, active repairs, completed, rejected).
- **All reports** — searchable, filterable, paginated management table with per-row actions.
- **Verification** — verify / mark duplicate / reject (with reason); the AI confidence stays separate from the official decision; reviewer + timestamp are recorded.
- **Priority** — Critical / High / Medium / Low (authoritative, not model-driven).
- **Assignment** — assign a maintenance team with a target date.
- **Repair tracking** — validated status transitions; **resolving requires repair evidence** uploaded through the backend.
- **Map** — all reports with valid coordinates, filtered by status/priority.
- **Analytics** — reports by status/priority/area (hotspots) and average submit→verify and assign→complete times computed from stored timestamps.
- **Teams** — create and toggle maintenance teams.
- **Profile** — read-only identity + sign out.

Access is enforced by the backend role check (`government_authority`), never by
hiding a button.

## 9. Firebase data model

| Collection | Purpose | Key fields |
|-----------|---------|-----------|
| `users/{uid}` | Profile + role | `display_name, email, role (user \| government_authority), account_status, *_at` |
| `reports/{id}` | A pothole report | `reporter_uid, media_type, detections, pothole_count, max_confidence, location{latitude,longitude}, address, description, category, original_object, annotated_object, status, priority, assigned_team_id/name, verified_by/at, completed_at, *_at` |
| `reportHistory/{id}` | Append-only audit | `report_id, event, previous, new, actor_uid, reason, created_at` |
| `maintenanceTeams/{id}` | Repair crews | `name, contact_email, jurisdiction, active` |
| `notificationLogs/{id}` | Email attempts | `report_id, event, recipient, delivered, created_at` |

Storage layout: `reports/{id}/{original|annotated|repair-evidence}/…` and
`detection_uploads/{uid}/…`.

## 10. Authentication and security

- Users register/login via the **Firebase Web SDK**; every protected API call
  sends the Firebase **ID token**, verified server-side with the Admin SDK.
- The **role is read from Firestore** (`users/{uid}.role`) — never trusted from
  the client. A custom Auth claim is also set by the admin script so rules that
  inspect `request.auth.token.role` pass.
- **IDOR protection:** a user can only read their own reports; authority users
  read all.
- **Status transitions** are validated on the backend (invalid ones return `409`).
- **Privileged writes** (verify/assign/priority/status/evidence) go through the
  backend Admin SDK — not direct client database writes.
- `firestore.rules` / `storage.rules` deny client writes to workflow fields and
  keep report media non-public (read via short-lived signed URLs).
- Upload limits, content validation, generated storage names, path-traversal
  protection, CORS restricted to configured origins, and secrets only in the
  environment.

## 11. Firebase configuration

1. Create a Firebase project at https://console.firebase.google.com.
2. Enable **Authentication → Email/Password**.
3. Create a **Cloud Firestore** database and a **Storage** bucket.
4. Download the **service-account key** JSON and place it at
   `backend/service-account.json` (kept out of Git).
5. Copy the **web app config** values into `backend/.env` (`FIREBASE_API_KEY`,
   `FIREBASE_AUTH_DOMAIN`, `FIREBASE_PROJECT_ID`, storage bucket, sender id,
   app id).
6. Deploy the security rules:
   ```bash
   firebase deploy --only firestore:rules,storage --project <your-project-id>
   ```

### Creating the first authority account

There are three ways to get a `government_authority` account:

1. **Self-register from the app** — on the Register tab choose *Government
   Authority* and enter the shared `AUTHORITY_SIGNUP_CODE` (set in `backend/.env`).
2. **Seed a ready-to-use login** (handy for demos; uses the service account and
   does not depend on client Firestore rules):
   ```bash
   cd backend
   python -m scripts.seed_authority
   # default: authority@example.com / Authority@2026 (or pass your own email + password)
   ```
3. **Promote an existing citizen** who already registered:
   ```bash
   cd backend
   python -m scripts.grant_authority official@example.com
   # revoke with: python -m scripts.grant_authority official@example.com --revoke
   ```

## 12. Google Maps / GPS

Maps use **Leaflet + OpenStreetMap** by default, which works with **no API key**.
`GOOGLE_MAPS_API_KEY` remains optional for teams that prefer Google Maps and is
exposed to the front-end only through `/api/config` (a browser-visible, key that
must be restricted by referrer/API in Google Cloud Console). GPS comes from the
browser Geolocation API; permission denial is handled gracefully. Precise GPS is
not assumed.

## 13. Model weights

The detection service expects trained YOLO `.pt` weights that actually contain a
**pothole class**. `.pt` files are **not committed** (large and git-ignored), so
you must place one before detection works. The generic `yolov8n.pt` is a COCO
model with **no pothole class** — it labels cars/people, never potholes.

**Quick way — download a pothole fine-tuned model:**
```bash
cd backend
pip install huggingface_hub
python -c "from huggingface_hub import hf_hub_download; hf_hub_download('Harisanth/Pothole-Finetuned-YOLOv8', 'best.pt', local_dir='models')"
# then copy/rename models/best.pt to models/pothole_yolov8.pt (the path .env expects)
```
`YOLO_MODEL_PATH` in `backend/.env` points at `models/pothole_yolov8.pt`.

**Class filtering.** `POTHOLE_CLASS_NAMES` (default `pothole`) lists the class-name
keywords that count as a pothole. Detections of any other class are ignored and
never annotated, so even a multi-class road-damage model only reports genuine
potholes here.

**Or train your own** with the `Pothole detection.v1i.yolov8` dataset referenced
in `.gitignore`:
```bash
yolo train model=yolov8n.pt data=pothole.yaml epochs=50 imgsz=640
```

Until valid weights exist, `/api/health` reports `model_ready: false` and the
detection endpoints return `503` with guidance — never fake detections.

## 14. Environment variables

Copy `backend/.env.example` to `backend/.env` and fill in values. Key groups:
application/CORS, YOLO (model path, thresholds, video limits), upload limits,
Firebase (project id, service-account path, public web config), Google Maps key,
and SMTP email (`EMAIL_ENABLED`, host/port/username/password/from, authority
inbox). `EMAIL_ENABLED=false` is the safe local default so no real emails are
sent.

## 15. Installation

```bash
# from the "Pothole Detection System" folder
cd backend
python -m venv venv
# Windows PowerShell:
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> Torch note: on Windows/macOS install a CPU wheel that matches your machine
> from https://pytorch.org/get-started/locally/ (the pinned torch line in
> `requirements.txt` is Linux-only to avoid a broken default install).

## 16. Running locally

```bash
cd backend
copy .env.example .env   # then edit values   (cp on macOS/Linux)
uvicorn app.main:app --reload --port 8000
```

The backend also serves the frontend at the same origin:

- http://127.0.0.1:8000/            → landing + login/register
- http://127.0.0.1:8000/user.html  → user dashboard (after login)
- http://127.0.0.1:8000/authority.html → authority dashboard
- http://127.0.0.1:8000/docs       → interactive OpenAPI docs

> Camera capture requires **HTTPS or localhost** (browser rule).

## 17. API endpoints

| Method | Path | Access |
|--------|------|--------|
| GET | `/api/health` | public |
| GET | `/api/config` | public (non-secret) |
| POST | `/api/detection/image?store=true\|false` | user |
| POST | `/api/detection/video` | user |
| POST | `/api/reports` | user |
| GET | `/api/reports/my` | user |
| GET | `/api/reports/nearby` | user |
| GET | `/api/reports/{id}` | owner/authority |
| GET | `/api/reports/{id}/history` | owner/authority |
| GET | `/api/authority/reports` | authority |
| GET | `/api/authority/analytics` | authority |
| POST | `/api/authority/reports/{id}/verify` | authority |
| POST | `/api/authority/reports/{id}/reject` | authority |
| PATCH | `/api/authority/reports/{id}/priority` | authority |
| POST | `/api/authority/reports/{id}/assign` | authority |
| PATCH | `/api/authority/reports/{id}/status` | authority |
| POST | `/api/authority/reports/{id}/evidence` | authority |
| GET/POST/PATCH | `/api/authority/maintenance-teams[/…]` | authority |

## 18. Testing

The suite runs **without Firebase credentials or model weights** (Firestore and
the model loader are faked; auth is overridden):

```bash
cd backend
pip install pytest httpx python-multipart firebase-admin email-validator
pytest
```

Covered: file validation, no-fabrication when weights are missing, health/config
shape, report submission + validation + ownership, IDOR blocking, status-transition
validity, evidence-required resolution, priority/assign lifecycle, analytics,
history/audit creation, and role enforcement. Model-level tests that use real
weights are intentionally separated and skipped unless you provide them.

## 19. Deployment

- **Backend:** containerise `backend/` (Uvicorn) or deploy to any Python host;
  set the environment variables and mount the service-account securely.
- **Frontend:** served by the backend, or host `Frontend/` on Firebase Hosting
  (point `FRONTEND_ORIGINS`/CORS at the hosting domain).
- **Rules:** `firebase deploy --only firestore:rules,storage`.
- Always use **HTTPS in production** (camera + geolocation require it).

## 20. Current limitations

- A trained pothole `.pt` model is **not** bundled (git-ignored); download or
  train one and point `YOLO_MODEL_PATH` at it (see [Model weights](#13-model-weights)),
  otherwise detection returns a clear `503`.
- Firebase credentials, the Maps key and SMTP settings are **not** present; all
  related features fail with clear, actionable messages instead of fake data.
- Video detection counts are per-frame; no multi-object tracking/deduplication
  across frames yet.
- Front-end loads Firebase/Leaflet from CDN **without Subresource Integrity
  (SRI)** hashes; pin SRI or self-host these scripts for hardened deployments.
- Jurisdiction-scoped access for multiple authorities is designed for but not
  enforced (single authority scope in v1).

## 21. Future enhancements

- Cross-frame tracking for unique pothole counts and heatmap depth analysis.
- Background job queue for long videos (Celery/RQ) with progress polling.
- Firebase Cloud Messaging push alerts in addition to email.
- Per-jurisdiction authority scoping and report de-duplication.
- Model evaluation metrics + A/B testing of model versions.

---

*No fabricated screenshots, accuracy figures or detection results are included;
run the app with real model weights and credentials to see genuine output.*
