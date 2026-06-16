# CEU Compliance & Certificate Automation Portal

A working multi-format CEU compliance portal with a Flutter Web enterprise dashboard and FastAPI/PostgreSQL backend.

## Included Workflow

- JWT login for Admin and Dealer/Presenter roles
- Event creation and role-scoped event access
- Registration, attendance, post-test, and survey uploads from CSV, XLSX, PNG, JPG, or JPEG
- Name/email normalization and cross-file attendee matching
- Eligibility engine requiring attendance, completed post-test with a score of at least 80%, and a valid email (the feedback survey is tracked and encouraged but does not block certificates)
- Admin approvals
- PDF certificate generation
- SMTP delivery or safe local email-log mode
- Certificate resend history and timestamps
- Attendee search, audit log viewer, and annual CSV report export
- Source files, decisions, certificates, and email attempts retained in PostgreSQL/storage for the configured 7-year policy

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

## Production Notes

- Replace `SECRET_KEY` and seed passwords.
- Restrict CORS to the deployed web origin.
- Set `EMAIL_DELIVERY_MODE=smtp` and configure SMTP variables.
- Put retained storage on encrypted durable storage with backup and lifecycle controls.
- Terminate TLS at a reverse proxy/load balancer.
- Run Alembic migrations as a controlled deployment step.
- Use managed PostgreSQL backups and verify the 7-year retention policy with your compliance owner.
