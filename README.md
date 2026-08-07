# CEU Compliance & Certificate Automation Portal

<!-- Replace OWNER/REPO with the GitHub path once the repo is pushed. -->
[![CI](https://github.com/OWNER/REPO/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/ci.yml)

A working multi-format CEU compliance portal with a Flutter Web enterprise dashboard and FastAPI/PostgreSQL backend.

## Architecture

- **Backend** — FastAPI + SQLAlchemy served by Uvicorn (`backend/`), with Alembic migrations and a seed script that create the schema and starter accounts on boot. Uploads (CSV/XLSX/PNG/JPG) are normalized by the import pipeline; image files go through local Tesseract OCR.
- **Database** — PostgreSQL is the system of record (attendees, events, eligibility decisions, certificate metadata, email attempts, audit log). Tests run against in-memory SQLite so they need no running database.
- **Frontend** — Flutter web app (`frontend/`), compiled to a static bundle and served by nginx (Docker), `python -m http.server` (`start.sh`), or Vercel (see `DEPLOYMENT.md`). It talks to the API via the compile-time `API_BASE_URL` dart-define.
- **Storage layout** — retained file bytes live under `backend/storage/`: `uploads/` (original source files) and `certificates/` (generated PDFs). In Docker this is the `retained_files` volume mounted at `/app/storage`; set `STORAGE_DIR` to relocate it.
- **CI** — GitHub Actions (`.github/workflows/ci.yml`) runs backend pytest and Flutter analyze/test on every push and pull request.

## Included Workflow

- JWT login for Admin and Dealer/Presenter roles
- Event creation and role-scoped event access
- Registration, attendance, post-test, and survey uploads from CSV, XLSX, PNG, JPG, or JPEG
- Name/email normalization and cross-file attendee matching
- Eligibility engine requiring attendance, a valid email, and — on events configured to require them — a post-test scored at least 80% and a completed feedback survey. Both requirements are explicit per-event flags (`test_required`, `survey_required`); the post-test one defaults to on, so an event never starts granting credit without one by accident. An event that requires a post-test but has none configured reports a setup warning, because otherwise every attendee stays permanently ineligible.
- Post-test scores are read with the unit decided once per column (percentages, `x/10`, or `x/1`). A column that is entirely 0–10 with no `%` and no fraction is genuinely ambiguous — `8` could be 8% or 8/10 — so the import refuses it and asks, rather than guessing a failing score into a passing one.
- Admin approvals
- PDF certificate generation
- SMTP delivery or safe local email-log mode
- Certificate resend history and timestamps
- Attendee search, audit log viewer, and annual CSV report export
- Source files, decisions, certificates, and email attempts retained in PostgreSQL/storage for the configured 7-year policy. The retention floor is enforced, not just documented: an event holding a delivered certificate inside its window cannot be deleted, and withdrawing a certificate issued in error revokes it — the record and its number survive, and public verification reports it as revoked — rather than destroying the record. Purging expired records is an operator-run step (`python -m app.services.retention`, dry-run by default) rather than an automatic background job, so removing compliance records is always a reviewed action.

## One-Command Local Start (no Docker)

With PostgreSQL running and the Flutter SDK installed:

```bash
./start.sh
```

This migrates and seeds the database, starts the API on `http://127.0.0.1:8000`, and serves the
web portal on `http://127.0.0.1:8090`. With both servers up, `python3 scripts/e2e_smoke.py`
exercises the full workflow (event → uploads → public test/survey → approval → certificate →
distribution → reports) end to end.

## Quick Start With Docker

Install Docker Desktop, then run:

```bash
docker compose up --build
```

Open:

- Portal: `http://localhost:8080`
- API documentation: `http://localhost:8000/docs`

Seed credentials:

- Admin: `admin@example.com` / `Admin123!`
- Dealer/Presenter: `presenter@example.com` / `Presenter123!`

## Local Development

### Backend

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload --port 8000
```

PostgreSQL must be available using the `DATABASE_URL` in `backend/.env`.

### Flutter Web

Install the Flutter stable SDK, then:

```bash
cd frontend
flutter pub get
flutter run -d chrome --web-port 8080 --dart-define=API_BASE_URL=http://localhost:8000/api
```

## Sample Data

Upload the four files in `sample_data/` to the seeded event in this order:

1. `registration_roster.csv`
2. `attendance_sign_in.csv`
3. `post_test_results.csv`
4. `survey_results.csv`

The sample intentionally includes an eligible attendee, a failing score, missing survey completion, missing attendance, and an invalid email.

Image uploads use local Tesseract OCR and work best with clean printed tables or comma-separated screenshots. CSV/XLSX remains the most reliable source format.

## Troubleshooting

- **PostgreSQL is not running / connection refused** — `start.sh` checks with `pg_isready` and exits early. Start Postgres (e.g. `brew services start postgresql@16`) and confirm the `DATABASE_URL` in `backend/.env` matches your local database, user, and password. With Docker Compose the `db` service is started for you.
- **Image uploads fail (Tesseract missing)** — PNG/JPG parsing needs the Tesseract binary on the backend machine: `brew install tesseract` (macOS) or `apt-get install tesseract-ocr` (Debian/Ubuntu). The Docker image installs it already. CSV/XLSX uploads work without it.
- **Browser console shows CORS errors** — the origin serving the web app must be listed in `BACKEND_CORS_ORIGINS` (comma-separated, exact scheme + host + port, e.g. `http://127.0.0.1:8090`). Note `localhost` and `127.0.0.1` are different origins. Restart the API after changing it.
- **Frontend loads but every request fails** — the API base URL is baked in at build time via `--dart-define=API_BASE_URL=...`; rebuild the web bundle if the backend address changed (delete `frontend/build/web` so `start.sh` rebuilds).
- **Stale backend dependencies or frontend build** — `start.sh` reuses `backend/.venv` and `frontend/build/web` when they exist; delete either directory to force a rebuild.

## Production Notes

- Replace `SECRET_KEY` and seed passwords.
- Restrict CORS to the deployed web origin.
- Set `EMAIL_DELIVERY_MODE=smtp` and configure SMTP variables.
- Put retained storage on encrypted durable storage with backup and lifecycle controls.
- Terminate TLS at a reverse proxy/load balancer.
- Run Alembic migrations as a controlled deployment step.
- Use managed PostgreSQL backups and verify the 7-year retention policy with your compliance owner.
