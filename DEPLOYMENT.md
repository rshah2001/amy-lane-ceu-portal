# Deployment — Free-Tier Cloud Staging

This deploys the CEU portal as a **demo Amy can try from a live URL**. It is **not** the
system of record for real attendee PII or 7-year retention — free tiers sleep/pause and are
not compliance-grade. Move to a secured/paid tier (see bottom) before storing real data.

```
                 ┌─────────────────────┐
   Browser  ───► │  Vercel (frontend)  │   Flutter web (static)
                 └──────────┬──────────┘
                            │  HTTPS  /api/*
                 ┌──────────▼──────────┐
                 │  Render (backend)   │   FastAPI + Uvicorn (Docker)
                 │  + /app/storage     │   ⚠ disk is EPHEMERAL on free tier
                 └──────────┬──────────┘
                            │  postgresql+psycopg
                 ┌──────────▼──────────┐
                 │ Supabase (Postgres) │   DB system of record for the demo
                 └─────────────────────┘
        Email: Gmail SMTP (nmeda.newsletter.bot@gmail.com)
```

You must perform the account logins yourself (I can't authenticate to your Vercel/Render/
Supabase accounts). Each step below is something you run; ping me if a step errors.

---

## 1. Database — Supabase (Postgres)
1. Create a project at supabase.com (free tier). Pick a strong DB password.
2. **Project Settings → Database → Connection string → URI.** Copy it.
3. Change the scheme `postgresql://` → `postgresql+psycopg://`. Prefer the **pooler** URI
   (host `...pooler.supabase.com`, port `6543`). This is your `DATABASE_URL`.
4. Nothing else to do — the backend runs `alembic upgrade head` + seed on boot and creates
   all tables.

## 2. Backend — Render (Docker)
1. Push this repo to GitHub.
2. Render → **New → Blueprint**, select the repo. It reads `render.yaml`.
3. Fill the `sync: false` env vars when prompted:
   - `DATABASE_URL` — from step 1
   - `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_FROM` — the Gmail bot + app password
   - `BACKEND_CORS_ORIGINS` / `PUBLIC_FRONTEND_URL` — set after step 3 (Vercel URL); redeploy.
   (`SECRET_KEY` is auto-generated; `EMAIL_DELIVERY_MODE=smtp` etc. are preset.)
4. Deploy. Confirm `https://<your-api>.onrender.com/api/health` returns `{"status":"ok"}`.
   Note: the free instance **sleeps after ~15 min idle**; first request after sleep is slow.

## 3. Frontend — Vercel (static Flutter web)
Vercel has no Flutter SDK, so build locally and deploy the static output:
```bash
cd frontend
flutter build web --release \
  --dart-define=API_BASE_URL=https://<your-api>.onrender.com/api
npx vercel deploy --prod          # uses frontend/vercel.json (serves build/web)
```
Then go back to Render and set `BACKEND_CORS_ORIGINS` and `PUBLIC_FRONTEND_URL` to the
Vercel URL (e.g. `https://ceu-portal.vercel.app`) and redeploy the backend.

## 4. Verify
- Visit the Vercel URL → log in as admin → create an event, assign a presenter.
- `https://<vercel-url>/?verify=<cert-number>` → public verification page (no login).
- Send a test certificate to your own email to confirm Gmail delivery in prod.

## 5. Credentials
Seed creates: admin `admin@example.com` / `Admin123!`, presenter `presenter@example.com` /
`Presenter123!`. **Change these immediately** in prod (Users page / reset). For Amy, create
her own admin from the Users page.

---

## File storage — Supabase Storage (recommended) or local disk
The backend stores file bytes (uploaded rosters/sign-in sheets, OCR images, certificate
templates, generated certificate PDFs) through a storage abstraction
(`backend/app/services/storage.py`) with two backends:

- **Supabase Storage** (durable, recommended for any hosted deploy) — used when all three
  env vars below are set. Files live in a Supabase bucket; the local `/app/storage` disk is
  only a serving cache and is transparently re-hydrated from the bucket after an
  ephemeral-disk restart.
- **Local disk** (dev fallback) — used when the env vars are unset. Files are written under
  `STORAGE_DIR` exactly as before; on Render's free tier that disk is **ephemeral**, so
  original uploads are lost on redeploy (certificate PDFs can still be regenerated from
  their immutable DB snapshots).

To enable Supabase Storage:
1. In the Supabase project (same one as the database, or a separate one): **Storage →
   New bucket**. Name it (e.g. `ceu-files`) and leave **"Public bucket" OFF**.
   ⚠ **The bucket must be private** — it holds attendee PII and certificates (protected
   info under the compliance requirements). Files are served only through the API's
   authenticated endpoints using the service-role key; there are no public bucket URLs.
2. Set these env vars on the backend (Render → Environment):
   - `SUPABASE_URL` — the project URL, e.g. `https://<ref>.supabase.co`
     (Project Settings → API).
   - `SUPABASE_SERVICE_ROLE_KEY` — the **service_role** secret key (Project Settings →
     API). Treat it like a DB password; backend-only, never in the frontend.
   - `SUPABASE_STORAGE_BUCKET` — the bucket name from step 1, e.g. `ceu-files`.
3. Redeploy. No migration is needed: object keys mirror the on-disk layout
   (`uploads/<event_id>/…`, `certificates/…`), and any file missing from the bucket
   (pre-existing certs) is regenerated or re-uploaded on next write.

## Moving to a secured tier (before real PII)
- Paid Render (no sleep, persistent disk) or a VPS with encrypted disk + backups.
- Managed Postgres with PITR backups; verify the 7-year retention policy with the compliance owner.
- Restrict `BACKEND_CORS_ORIGINS` to the exact frontend origin; keep TLS everywhere (both
  Vercel and Render terminate HTTPS automatically).
- Rotate `SECRET_KEY` and all seed passwords; store secrets only in the platform's env store.
