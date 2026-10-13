# University Facial Recognition Attendance System

Working Django/DRF + React application for **teacher-operated, individual webcam attendance**. Students are records, not accounts. Admins manage master data; teachers only access assigned sections. Recognition proposes an identity; only an explicit teacher confirmation writes attendance. Manual check-in and corrections require an audit reason.

## Quick start: manual milestone (no AI downloads)

Requires Python **3.11**, Node **22+**, npm. Commands below are PowerShell from this project root. Use `npm.cmd` on Windows if execution policy blocks `npm.ps1`.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.lock.txt
.\.venv\Scripts\python.exe backend\scripts\init_env.py
Copy-Item frontend\.env.example frontend\.env
.\.venv\Scripts\python.exe backend\manage.py migrate
$env:DEMO_PASSWORD = 'choose-your-own-long-demo-password'
.\.venv\Scripts\python.exe backend\manage.py seed_demo
.\.venv\Scripts\python.exe backend\manage.py runserver 127.0.0.1:8000
```

In a second terminal:

```powershell
cd frontend
npm.cmd ci
npm.cmd run dev
```

Open **http://localhost:5173**, log in as `teacher` or `admin` with your seed password. The seed creates five fictional students, sections A/B, assigned teachers and a schedule for today. `other-teacher` sees B only. Existing passwords are preserved when reseeding. Seed contains no biometric data. `backend/.env` uses SQLite for this lightweight demo; the deployment stack uses PostgreSQL.

For a command-line runnable demo after seed:

```powershell
.\.venv\Scripts\python.exe backend\manage.py demo_manual
```

It starts the scheduled class, manually checks in one student, closes, marks the other four absent and prints percentages. One schedule occurrence can only be used once. Rerun `seed_demo` to create a fresh current-time schedule for another demo. Use the UI for an interactive session instead of consuming that same occurrence with the CLI first.

If this workspace already contains the project-local runtime installed during development, `.venv\Scripts\python.exe` is ready and the first two commands can be skipped. `.tools` and `.venv` are ignored local artifacts, not required source files.

## Full CPU stack: PostgreSQL + Redis + ArcFace worker

Docker Desktop with Linux containers is the easiest complete setup. First generate `backend/.env` as above. `frontend/.env.example` contains only a public API URL, no secrets. Compose overrides the local database and Redis URLs without changing your local `.env`.

```powershell
$env:POSTGRES_PASSWORD = 'choose-a-random-db-password'
docker compose build
docker compose up -d db redis
docker compose run --rm backend python manage.py migrate
docker compose run --rm -e DEMO_PASSWORD='choose-your-own-long-demo-password' backend python manage.py seed_demo
docker compose up -d
```

Visit http://localhost:5173. Only frontend/backend are bound to loopback; database/Redis are private to the Compose network. Worker uses CPU, concurrency 1, and the [official PyTorch CPU wheel channel](https://pytorch.org/get-started/previous-versions/), avoiding CUDA package downloads. First real recognition/enrollment downloads ArcFace and anti-spoof weights into the private volume and may take several minutes. TensorFlow and PyTorch make this build large; keep at least several GB available. Subsequent frames reuse loaded models. Raw 640×480 JPEG webcam frames are uploaded one at a time. No client-side detector, embedding or client timestamp is trusted. Polling is used; WebSockets are not necessary.

Without Docker, install local PostgreSQL and Redis; set `DATABASE_URL=postgresql://...` and `CELERY_BROKER_URL=redis://localhost:6379/0`, install `backend/requirements-ai.txt` (the Linux transitive lock is `requirements-ai.lock.txt`), migrate, then run:

```powershell
cd backend
..\.venv\Scripts\python.exe -m celery -A config worker --pool=solo --concurrency=1 --loglevel=warning
# In another terminal, also from backend:
..\.venv\Scripts\python.exe -m celery -A config beat --loglevel=warning --schedule=private/celerybeat-schedule
```

Celery solo works on Windows. Gunicorn is used in the Linux image; Django runserver is local development only. `DJANGO_DEBUG` is namespaced to avoid collisions with unrelated system `DEBUG` variables.

## Runnable milestones

1. **Models/auth/seed:** `migrate`, `seed_demo`, staff login, browse assigned sections; admin manages users/departments/courses/sections/schedules/students/memberships. Django 5.2 LTS is pinned to the [current 5.2 security patch](https://www.djangoproject.com/download/) verified during implementation.
2. **Manual attendance:** start today’s schedule within 15 minutes before the class or during it; select a student and reason → Manual check-in. Count increments. Close → remaining snapshot students absent. Corrections require an existing record and a reason; available after closure.
3. **Enrollment:** Enrollment tab → select roster student → create 30-minute single-use link. Share it with that student. No login needed; only enrollment is possible. Link capability is in the URL fragment and is removed from browser history after loading. Submit consented live selfie. Alternatively authorized staff can upload 1–10 photos for a selected student with recorded consent. One request is one capture event. Links are consumed only after successful atomic storage. Photos/embeddings never appear in REST responses.
4. **Offline recognition:** with AI dependencies, real consented enrollment and trained classifier, run `python manage.py recognize_photo --section 1 --photo path/to/live-selfie.jpg` from backend. It checks liveness and prints proposal/cosine score only. For a template-only development demo set `REQUIRE_CLASSIFIER=0` temporarily; production should keep `1`.
5. **Async webcam:** start class → Enable camera → student approaches alone → Capture student → CPU worker → review name and cosine similarity → **Confirm identity & save**. Failed liveness, multiple/no faces, poor quality, unknown/uncertain, stale classifier, queue failure or missing weights cannot write attendance. Discarding a suggestion in the UI leaves it unused until expiry.
6. **Dashboard:** session roster/counts, date × student grid, percentages/flags, history and audit events. Use review-session dropdown for closed records/corrections. No student portal.
7. **Exports:** Grid → choose month, or leave blank for the section’s semester → Download Excel. Export has individual class occurrences, attended count, eligible denominator, percentage and threshold flags plus definitions. Safe text prevents Excel formula injection.
8. **Required trained classifier:** collect at least **3 independent capture events per student**, at least two students, preferably multiple samples per event on separate days. Do not split near-identical frames from one capture into independent events. Run `python manage.py train_classifier` (or `docker compose exec backend python manage.py train_classifier`). Frozen, normalized 512-dimensional ArcFace embeddings → sklearn logistic regression. Latest capture group per student is held out; all groups are disjoint across training/test. Training prints actual held-out accuracy, macro precision/recall/F1, per-student values and confusion matrix. Admin can inspect the report. No training on held-out samples after scoring. Unknown rejection still requires cosine threshold + margin and classifier/template agreement. A global classifier prediction outside the roster is rejected, never reassigned to a roster identity. Enrollment/expiry/deletion changes invalidate the model fingerprint; retrain. Closed-set accuracy is not a measure of unknown rejection or spoof resistance.
9. **Security/edge tests:** commands and hardware evaluation below.

## Tests and validation

```powershell
.\.venv\Scripts\python.exe backend\manage.py test attendance --settings=config.test_settings --verbosity=2
.\.venv\Scripts\python.exe backend\manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe backend\manage.py check
cd frontend
npm.cmd run build
```

For a live HTTP milestone, run both local servers, set `DEMO_PASSWORD` to the seeded password, run `seed_demo` for a fresh schedule, then `python backend/scripts/smoke_http.py`. It exercises real cookie/CSRF login, section scoping, start/manual/duplicate/closure, percentages and Excel download. It deliberately records a demo class. Backend/frontend `.env` files exist locally and are ignored; examples are tracked. Direct dependencies are pinned, transitive backend lockfiles and frontend `package-lock.json` provide reproducible installs.

Tests cover staff permissions, unauthenticated restrictions/CSRF, teacher assignment, snapshot roster membership, enrollment single use/consent/no attendance, duplicates, mandatory fresh confirmation, server timestamps, grace boundary, late/absence rules, percentages, protected exports, encrypted storage, consent withdrawal, memory upload bounds, retention, queue/AI failures, the complete capture/poll/confirm API, DeepFace adapter liveness/ArcFace contracts and synthetic grouped classifier mechanics. Synthetic vectors and mocks **do not measure real face recognition accuracy**. Use PostgreSQL to exercise row locks and database uniqueness under actual simultaneous requests:

```powershell
docker compose run --rm -e TEST_POSTGRES=1 backend python manage.py test attendance --settings=config.test_settings
```

This selects the Compose PostgreSQL database (test DB created by Django). Never point tests at a production database. SQLite does not implement row-level locking; it is suitable for single-operator local demonstrations.

### Required laptop evaluation (record outcomes, never invent results)

Use consented held-out captures and a separate unknown-person cohort. Start with adequate front lighting, then test dim/backlit, blurred, off-center, occluded, two-face and empty frames. Test printed photo and phone-screen replay: reject or record any attack acceptance; passive single-frame anti-spoofing is not a guarantee against sophisticated replay. Verify unknown people and students from another section are rejected. Confirm low-score/margin events appear in audit. Close the class while a worker processes a frame, let a review/grant expire, retry a confirmation, stop Redis, remove weights and try invalid/corrupt uploads. Attendance must remain unchanged until a fresh authorized confirmation. Log rejection rates, false accepts/rejects, CPU latency and lighting; tune thresholds on a **separate validation set**, then report untouched test results. If photo-spoof testing fails, use manual attendance pending stronger liveness. These physical checks have not been performed in this workspace.

## API and calculation contract

Cookie session auth with CSRF. Fetch `GET /api/auth/csrf/`, send returned token in `X-CSRFToken` on unsafe staff methods with credentials included. Login also requires CSRF. `POST /api/auth/login/`, `GET/DELETE /api/auth/me/`. Students cannot authenticate.

| Endpoint | Authorization / purpose |
| --- | --- |
| `/api/users/`, `/courses/`, `/departments/`, `/schedules/`, `/memberships/` | Admin master-data CRUD |
| `/api/sections/`, `/api/students/` | Assigned teacher reads; admin CRUD |
| `POST /api/sections/{id}/start/` with `schedule` | Assigned teacher/admin, today’s scheduled occurrence |
| `/api/sessions/{uuid}/manual/`, `/correct/`, `/close/` | Assigned teacher/admin; reason for manual/correction |
| `POST /api/sessions/{uuid}/capture-grant/` | Short-lived, single-use token bound to staff user + open session |
| `POST /api/sessions/{uuid}/capture/` | Multipart raw `frame` + `token`; creates async job only |
| `GET /api/jobs/{uuid}/` | Poll; job requester in assigned section; admin can inspect all |
| `POST /api/sessions/{uuid}/confirm/` with `job` | Fresh review from same user/session; unique student/session record |
| `POST /api/students/{id}/enrollment-link/`, `/bulk-enroll/` | Assigned staff; cannot write attendance |
| `POST /api/enroll/` | Public capability-based enrollment only: `token`, `consent=true`, `photos` |
| `POST /api/students/{id}/purge-biometrics/` | Admin deletion/consent withdrawal, reason required |
| `GET /api/students/{id}/percentages/` | Protected; authorized student/section data only |
| `/api/sections/{id}/grid/`, `/export/` | Assigned staff; `month=YYYY-MM`, or ISO `start`/`end`, or section `semester` |
| `/api/audit/` | Admin all; teacher assigned section events only |
| `/api/classifier/` | Admin actual held-out report; HTTP 409 until trained/current |

**Percentage = 100 × (present + late) / eligible closed sessions.** A student is eligible only if in that session’s immutable roster snapshot; open classes and classes before membership are excluded. No eligible sessions → `null` percentage, not zero. Each scheduled class occurrence is one column even when several occur on one date. Late means server capture time **strictly later** than scheduled start + snapshotted grace minutes; equality is present. Confirmation time does not determine lateness. Manual attendance uses server time, with a reason. Absences are generated at closure. Current section threshold overrides course threshold; historical rosters and session grace/match thresholds are snapshots. Teachers can correct a closed record with audit history; original capture timestamp remains preserved.

## Architecture and security

`backend/attendance`: models, RBAC, audited attendance services, enrollment, reports, Celery tasks, REST, management commands and tests. `backend/recognition`: private cryptography/storage, OpenCV/DeepFace pipeline, sklearn grouped classifier. `frontend`: React/Vite staff UI and a capability-only selfie form. `compose.yaml`: PostgreSQL/Redis/backend/worker/beat/frontend. Read/update `gpt.md` for future work.

DeepFace calls use `extract_faces(anti_spoofing=True)` followed by `represent(model_name="ArcFace")` on the single verified aligned face. Reference: [serengil/deepface](https://github.com/serengil/deepface), pinned v0.0.93. Cosine similarity is an uncalibrated similarity, **not a probability**. Default thresholds are starting configuration, not validated operating points.

Environment-managed Fernet key encrypts photos, embeddings, frames and trained classifier artifact. DB stores only ciphertext for biometrics; private frame/artifact volume has no public HTTP routes. Never expose keys/embeddings. Keep key backups separate from database backups; losing the key loses biometric access. Host DB/storage operators remain privileged. Restrict filesystem permissions and encrypt disks/backups. AI library model weights are downloaded private artifacts, not student photos.

Captured frames are encrypted immediately, deleted by the worker even on rejection/error, and purged by beat after abandonment. Uploads stay in bounded memory (5 MB/file, 20 MB/request), never plaintext OS temporary files. Default review lifetime 300s, grant 90s, leftover frame retention 600s; biometric samples 365 days. `purge_private_data` runs cleanup on demand. Deployment must run beat or schedule equivalent cleanup. Admin removal revokes consent/unused links and deletes the encrypted classifier artifact; expiration/enrollment also invalidate it. Pending proposals cannot be confirmed after consent withdrawal. API responses use `Cache-Control: no-store, private`. Audit logs retain actor, event and minimal record changes/reasons, not images or embeddings. University must publish its approved consent, withdrawal, access and retention policy; this app includes an explicit versioned consent flow and manual alternative, not a jurisdiction-specific legal policy.

For use outside localhost: set `DJANGO_DEBUG=0`, strong `SECRET_KEY` and `BIOMETRIC_KEY`, production `ALLOWED_HOSTS`, HTTPS frontend origin, and HTTPS reverse proxy/TLS. Secure cookies, SSL redirect and HSTS are enabled when DJANGO_DEBUG is off. Forwarded-proto trust is deliberately not automatic; configure it only for a trusted proxy that strips user-supplied headers. Serve built frontend and Django static files with the proxy; Vite dev server is not a production web server. Add HTTPS, private network, access monitoring, reviewed dependencies, encrypted backups, persistent retention worker and physical classroom supervision before rollout. No remote/self-attendance endpoint exists; a network API cannot prove physical presence by itself, so restrict classroom network/teacher devices operationally. Authentication gives only teachers/admins capture authority.

## Scope and honest status

Implemented incremental runnable application, migrations, seed, manual demo, enrollment, offline/async recognition integration, UI, Excel reports, required classifier training/evaluation and security tests. Excludes student auth/dashboard, whole-room recognition, IoT and LMS. Optional neural/risk classifier and WebSockets are not implemented.

Executed locally: **28 backend tests passed, 2 PostgreSQL concurrency tests skipped**, migration/system checks, manual CLI demo, two live cookie/CSRF HTTP demos through Excel download, frontend production build and npm audit (zero advisories after Vite patch). Core dependency compatibility check and complete CPU AI dependency resolution passed. See `gpt.md` for remaining validation. Real ArcFace weights, webcam liveness tests, consented independent training samples and real held-out results require hardware/data. Docker/PostgreSQL execution and visual browser QA have not run here. Do not treat synthetic tests or an implemented pipeline as evidence of recognition accuracy or production readiness.
