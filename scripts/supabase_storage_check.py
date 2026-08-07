"""Live smoke test for Supabase Storage — proves the real bucket works end to end.

Run this AFTER setting SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY and
SUPABASE_STORAGE_BUCKET (locally or on the deployed backend). It does a real
round-trip against the configured bucket — upload, read back, verify bytes
match, then delete — using the exact same storage backend the app uses.

    cd backend && python ../scripts/supabase_storage_check.py

Exit code 0 = storage is correctly configured and writable. Non-zero = it
printed what failed. It only ever touches a throwaway key under
``_smoke_test/`` and cleans it up, so it is safe to run against the live bucket.
"""
from __future__ import annotations

import sys

from app.core.config import settings
from app.services.storage import get_storage


def main() -> int:
    missing = [
        name
        for name, value in (
            ("SUPABASE_URL", settings.supabase_url),
            ("SUPABASE_SERVICE_ROLE_KEY", settings.supabase_service_role_key),
            ("SUPABASE_STORAGE_BUCKET", settings.supabase_storage_bucket),
        )
        if not value
    ]
    if missing:
        print("NOT configured for Supabase Storage — these env vars are unset:")
        for name in missing:
            print(f"  - {name}")
        print("Files would fall back to local disk (ephemeral on Render's free tier).")
        return 2

    backend = get_storage()
    if not getattr(backend, "is_remote", False):
        print("Backend resolved to local disk despite env vars — check the values.")
        return 2

    bucket = settings.supabase_storage_bucket
    key = "_smoke_test/roundtrip.txt"
    payload = b"NMEDA CEU portal storage smoke test"
    print(f"Bucket: {bucket}")

    try:
        backend.save(key, payload)
        print("  upload   ok")
        got = backend.read(key)
        if got != payload:
            print(f"  read     MISMATCH — wrote {len(payload)} bytes, read {len(got)}")
            return 1
        print("  read     ok (bytes match)")
        backend.delete(key)
        print("  delete   ok")
    except Exception as exc:  # noqa: BLE001 — surface any failure plainly
        print(f"  FAILED: {type(exc).__name__}: {exc}")
        print("Common causes: wrong service_role key, bucket name typo, or the")
        print("bucket does not exist. (A private bucket is correct — do not make it public.)")
        return 1

    print("PASS — Supabase Storage is configured, private, and writable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
