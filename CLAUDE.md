# Working in this repository

A CEU compliance portal: FastAPI + PostgreSQL backend (`backend/`), Flutter Web
frontend (`frontend/`). It issues continuing-education certificates that are
records of professional standing, and it makes written retention commitments to
an accrediting body. That shapes almost every decision below — when correctness
and convenience conflict here, correctness wins and the user gets told why.

## Running things

```bash
./start.sh                      # API on :8000, portal on :8090, migrates + seeds
cd backend && .venv/bin/python -m pytest -q
cd frontend && flutter analyze && flutter test
python3 scripts/e2e_smoke.py    # needs both servers up
```

**The venv's console scripts have stale shebangs** (the project directory was
moved). Always invoke modules: `.venv/bin/python -m alembic`, never
`.venv/bin/alembic`. `start.sh` works around this already.

**Never run `alembic downgrade` against the `DATABASE_URL` in `backend/.env`.**
It has destroyed the development database before. Verify a migration roundtrip
on a throwaway: `createdb ceu_tmp && DATABASE_URL=...ceu_tmp .venv/bin/python -m alembic upgrade head` etc.

`.venv/bin/python -m scripts.check_migration_drift` must report no drift after
any model or migration change. CI runs it against real Postgres, because the
test suite builds its schema with `create_all` on SQLite and therefore never
executes a migration or enforces a foreign key.

## Invariants that are easy to break

These exist because breaking them produced a real, reproduced failure. Each is
commented at its site; this is the index.

**Never silently produce a plausible-but-wrong compliance outcome.** Two bugs
of exactly this shape shipped before: a post-test score of `8` was scaled to
`80.0` and passed someone who failed, and a question's answer key defaulted to
choice A so attendees who answered correctly were marked wrong. Both looked
like success. Where input is genuinely ambiguous, refuse and ask — see
`services/csv_import.py:resolve_score_basis`.

**An import that lands zero rows must not delete anything.** Parsing is
two-phase and the destructive reset runs inside a savepoint only once rows are
known to import (`services/csv_import.py`). A file that yields nothing is a
400, not a 201.

**Certificates reissue from `Certificate.event_snapshot`, never live event
data** (`services/certificates.py:reissue_certificate_pdf`). Editing an event
must not rewrite a document already in someone's hands.

**Withdrawal is revocation, not deletion.** An issued certificate inside the
retention window is marked revoked and kept, with its number still resolving in
the public verifier as revoked. The `EventAttendee` row survives too —
`certificates.event_attendee_id` is `NOT NULL ON DELETE CASCADE`, so deleting
the link destroys the certificate at the database level whatever the ORM
intends (`api/compliance.py:_revoke`).

**Retention is enforced in code, not just documented.** `retention_years` is
read live by both the deletion guard and the purge, so changing it immediately
changes what is destroyable. The purge is operator-invoked and dry-run by
default (`services/retention.py`) — deliberately not scheduled. The claims in
`docs/data-storage-and-retention-confirmation.md` are kept true by these
mechanisms; if you weaken one, that document becomes false.

**Eligibility requirements are explicit per-event flags** (`test_required`,
`survey_required`), both defaulting so credit is never granted by accident. An
event requiring a post-test with none configured reports a
`configuration_warning` rather than silently blocking its whole roster
(`services/compliance.py`).

**A password write bumps `User.token_version`** at the single place passwords
are written (`services/password_reset.py:set_password`), which is what
invalidates outstanding JWTs. Route it through there rather than hashing
directly.

**User-derived cells are escaped before they reach a CSV** (`services/csv_safe.py`).
The data originates from unauthenticated endpoints, and the export opens in
Amy's Excel.

**Public write endpoints are rate limited** through one shared limiter
(`core/rate_limit.py`), keyed per caller+scope+token so a whole classroom
behind one NAT address doesn't lock out the portal.

**Emailed links carry a per-attendee `invite_nonce`** which, when present, *is*
the identity — name matching is skipped entirely. Nonce-less submissions still
work: printed QR sheets are one shared link per room and a core feature.

## Frontend conventions

The design system is not decorative. `flutter analyze` must end at "No issues
found!", and tests assert **zero** hardcoded hex colors and **zero** `fontSize`
literals outside `core/theme.dart`. Use `Space.*`, `Theme.of(context).portal`,
and the text theme.

Accessibility is a functional requirement, not polish: NMEDA's industry is
vehicle modification for drivers with disabilities, and the public QR pages are
where its audience lands. `SemanticsBinding.instance.ensureSemantics()` in
`main()` is load-bearing — without it a CanvasKit build shows screen readers a
blank canvas. Use the primitives in `widgets/common.dart`: `Heading`,
`announceToScreenReader`, `validateAndFocusFirstError`, `MinTapTarget`,
`humanizeError`.

Every data view uses `widgets/portal_table.dart`. Its error state deliberately
hides rows rather than showing stale ones — acting on a roster that failed to
refresh is how the wrong person gets a certificate.

Never show a user `exception.toString()`; route it through `humanizeError`.

Long-lived requests use the `LatestRequest` mixin (`widgets/request_guard.dart`)
so a stale response cannot repaint a list whose buttons email real certificates.

## Deploying

The backend auto-deploys on push. **The Flutter frontend must be built locally
and deployed by hand** (`flutter build web --release --dart-define=API_BASE_URL=...`
then `vercel deploy`), or only half the change ships. See `DEPLOYMENT.md` for
the operational settings and the retention purge command.
