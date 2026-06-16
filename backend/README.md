# CEU Compliance API

FastAPI backend for CEU event compliance, certificate generation, email logging, and 7-year audit retention.

## Setup

1. Create PostgreSQL database and user:

```sql
CREATE DATABASE ceu_compliance;
CREATE USER ceu_user WITH PASSWORD 'ceu_password';
GRANT ALL PRIVILEGES ON DATABASE ceu_compliance TO ceu_user;
```

2. Install dependencies:

```bash
brew install tesseract
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

3. Run migrations and seed realistic users/event:

```bash
alembic upgrade head
python -m app.seed
```

4. Start the API:

```bash
uvicorn app.main:app --reload --port 8000
```

Open API docs at `http://localhost:8000/docs`.

## Environment Variables

See `.env.example`. In production, set a strong `SECRET_KEY`, configure `DATABASE_URL`, restrict `BACKEND_CORS_ORIGINS`, and set `EMAIL_DELIVERY_MODE=smtp` plus SMTP credentials.

By default, certificate email delivery is `log`, which records sent timestamps and provider IDs without contacting an SMTP server.

Uploads support CSV, XLSX, PNG, JPG, and JPEG. Image files are processed locally with Tesseract OCR and should be reviewed before approval.

## Seed Credentials

- Admin: `admin@example.com` / `Admin123!`
- Dealer/Presenter: `presenter@example.com` / `Presenter123!`
