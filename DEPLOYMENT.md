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

## Storage caveat (important)
File bytes (uploaded rosters/sign-in sheets, OCR images, generated certificate PDFs) are
written to `/app/storage` on the Render instance, whose disk is **ephemeral on the free
tier** — files reset on each deploy/restart. Certificate **metadata** (number, status,
recipient, audit) lives durably in Postgres, and certs can be regenerated, so this is fine
for a short demo. For durable file storage you have two clean options at the secured tier:
- **Render paid disk** (simplest — persistent volume mounted at `/app/storage`), or
- **Supabase Storage** (object store; requires routing certificate template + PDF read/write
  through a storage adapter and serving via signed URLs — a follow-up task, validated against
  the real Supabase project).

## Moving to a secured tier (before real PII)
- Paid Render (no sleep, persistent disk) or a VPS with encrypted disk + backups.
- Managed Postgres with PITR backups; verify the 7-year retention policy with the compliance owner.
- Restrict `BACKEND_CORS_ORIGINS` to the exact frontend origin; keep TLS everywhere (both
  Vercel and Render terminate HTTPS automatically).
- Rotate `SECRET_KEY` and all seed passwords; store secrets only in the platform's env store.
