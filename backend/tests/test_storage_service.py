"""Unit tests for the file-storage abstraction (app/services/storage.py).

LocalStorage is tested against a real temp directory. SupabaseStorage is
tested against a mocked httpx transport — no network involved.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings  # noqa: E402
from app.services import storage  # noqa: E402
from app.services.storage import (  # noqa: E402
    LocalStorage,
    StorageError,
    SupabaseStorage,
)

BUCKET = "test-bucket"
BASE = "https://project.supabase.co"


class TestLocalStorage:
    def test_save_and_read_roundtrip(self, tmp_path):
        backend = LocalStorage(tmp_path)
        backend.save("uploads/7/roster.csv", b"name,email\n")
        assert (tmp_path / "uploads" / "7" / "roster.csv").read_bytes() == b"name,email\n"
        assert backend.read("uploads/7/roster.csv") == b"name,email\n"

    def test_read_missing_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            LocalStorage(tmp_path).read("uploads/7/missing.csv")

    def test_delete_removes_file_and_tolerates_missing(self, tmp_path):
        backend = LocalStorage(tmp_path)
        backend.save("certificates/CERT-1.pdf", b"%PDF-fake")
        backend.delete("certificates/CERT-1.pdf")
        assert not (tmp_path / "certificates" / "CERT-1.pdf").exists()
        backend.delete("certificates/CERT-1.pdf")  # no error on repeat

    def test_delete_prefix_removes_tree(self, tmp_path):
        backend = LocalStorage(tmp_path)
        backend.save("uploads/9/a.csv", b"a")
        backend.save("uploads/9/b.csv", b"b")
        backend.save("uploads/10/keep.csv", b"keep")
        backend.delete_prefix("uploads/9")
        assert not (tmp_path / "uploads" / "9").exists()
        assert (tmp_path / "uploads" / "10" / "keep.csv").exists()


def make_supabase(handler) -> SupabaseStorage:
    return SupabaseStorage(
        BASE, "service-role-key", BUCKET, transport=httpx.MockTransport(handler)
    )


class TestSupabaseStorage:
    def test_save_posts_object_with_auth_and_upsert(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["method"] = request.method
            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("Authorization")
            seen["apikey"] = request.headers.get("apikey")
            seen["upsert"] = request.headers.get("x-upsert")
            seen["body"] = request.content
            return httpx.Response(200, json={"Key": f"{BUCKET}/uploads/3/a.csv"})

        make_supabase(handler).save("uploads/3/a.csv", b"hello")
        assert seen["method"] == "POST"
        assert seen["url"] == f"{BASE}/storage/v1/object/{BUCKET}/uploads/3/a.csv"
        assert seen["auth"] == "Bearer service-role-key"
        assert seen["apikey"] == "service-role-key"
        assert seen["upsert"] == "true"
        assert seen["body"] == b"hello"

    def test_save_error_raises_storage_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"message": "denied"})

        with pytest.raises(StorageError, match="403"):
            make_supabase(handler).save("uploads/3/a.csv", b"hello")

    def test_read_returns_bytes(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert str(request.url) == f"{BASE}/storage/v1/object/{BUCKET}/certificates/C-1.pdf"
            return httpx.Response(200, content=b"%PDF-bytes")

        assert make_supabase(handler).read("certificates/C-1.pdf") == b"%PDF-bytes"

    def test_read_404_raises_file_not_found(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"message": "not found"})

        with pytest.raises(FileNotFoundError):
            make_supabase(handler).read("certificates/missing.pdf")

    def test_read_server_error_raises_storage_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        with pytest.raises(StorageError):
            make_supabase(handler).read("certificates/C-1.pdf")

    def test_delete_tolerates_404(self):
        statuses = iter([200, 404])

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "DELETE"
            return httpx.Response(next(statuses), json={})

        backend = make_supabase(handler)
        backend.delete("uploads/3/a.csv")
        backend.delete("uploads/3/a.csv")  # already gone: no error

    def test_network_failure_raises_storage_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

        with pytest.raises(StorageError, match="request failed"):
            make_supabase(handler).read("uploads/3/a.csv")

    def test_delete_prefix_lists_recursively_and_bulk_deletes(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, request.url.path, request.content))
            if request.url.path == f"/storage/v1/object/list/{BUCKET}":
                prefix = json.loads(request.content)["prefix"]
                if prefix == "uploads/5":
                    return httpx.Response(
                        200,
                        json=[
                            {"name": "a.csv", "id": "id-1"},
                            {"name": "scans", "id": None},  # sub-folder
                        ],
                    )
                if prefix == "uploads/5/scans":
                    return httpx.Response(200, json=[{"name": "sheet.png", "id": "id-2"}])
                return httpx.Response(200, json=[])
            if request.method == "DELETE" and request.url.path == f"/storage/v1/object/{BUCKET}":
                return httpx.Response(200, json=[])
            raise AssertionError(f"unexpected request {request.method} {request.url}")

        make_supabase(handler).delete_prefix("uploads/5")
        deletes = [c for c in calls if c[0] == "DELETE"]
        assert len(deletes) == 1
        assert json.loads(deletes[0][2]) == {
            "prefixes": ["uploads/5/a.csv", "uploads/5/scans/sheet.png"]
        }

    def test_delete_prefix_with_no_objects_issues_no_delete(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.method)
            return httpx.Response(200, json=[])

        make_supabase(handler).delete_prefix("uploads/404")
        assert calls == ["POST"]  # just the list call


class TestBackendSelectionAndFacade:
    def test_local_backend_by_default(self):
        backend = storage.get_storage()
        assert isinstance(backend, LocalStorage)
        assert backend.root == Path(settings.storage_dir)

    def test_supabase_backend_when_configured(self, monkeypatch):
        monkeypatch.setattr(settings, "supabase_url", BASE)
        monkeypatch.setattr(settings, "supabase_service_role_key", "key-1")
        monkeypatch.setattr(settings, "supabase_storage_bucket", BUCKET)
        backend = storage.get_storage()
        assert isinstance(backend, SupabaseStorage)
        assert backend.bucket == BUCKET

    def test_partial_supabase_config_falls_back_to_local(self, monkeypatch):
        monkeypatch.setattr(settings, "supabase_url", BASE)
        monkeypatch.setattr(settings, "supabase_service_role_key", None)
        monkeypatch.setattr(settings, "supabase_storage_bucket", BUCKET)
        assert isinstance(storage.get_storage(), LocalStorage)

    def test_file_key_relative_to_storage_dir(self):
        path = settings.uploads_dir / "12" / "abc-roster.csv"
        assert storage.file_key(path) == "uploads/12/abc-roster.csv"

    def test_file_key_outside_root_raises(self, tmp_path):
        with pytest.raises(StorageError):
            storage.file_key(tmp_path / "elsewhere.csv")

    def test_save_bytes_local_writes_file(self):
        destination = settings.uploads_dir / "31" / "sheet.csv"
        storage.save_bytes(destination, b"row\n")
        assert destination.read_bytes() == b"row\n"

    def test_save_bytes_remote_writes_bucket_and_local_cache(self, monkeypatch):
        uploaded = {}

        def handler(request: httpx.Request) -> httpx.Response:
            uploaded[request.url.path] = request.content
            return httpx.Response(200, json={})

        monkeypatch.setattr(storage, "get_storage", lambda: make_supabase(handler))
        destination = settings.uploads_dir / "32" / "sheet.csv"
        storage.save_bytes(destination, b"remote\n")
        assert uploaded == {f"/storage/v1/object/{BUCKET}/uploads/32/sheet.csv": b"remote\n"}
        assert destination.read_bytes() == b"remote\n"  # local serving cache

    def test_ensure_local_fetches_missing_file_from_remote(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"restored")

        monkeypatch.setattr(storage, "get_storage", lambda: make_supabase(handler))
        path = settings.certificates_dir / "RESTORE-1.pdf"
        assert not path.exists()
        assert storage.ensure_local(path) is True
        assert path.read_bytes() == b"restored"

    def test_ensure_local_missing_everywhere_returns_false(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={})

        monkeypatch.setattr(storage, "get_storage", lambda: make_supabase(handler))
        assert storage.ensure_local(settings.certificates_dir / "GONE.pdf") is False

    def test_ensure_local_is_plain_existence_check_for_local_backend(self):
        path = settings.uploads_dir / "33" / "present.csv"
        assert storage.ensure_local(path) is False
        storage.save_bytes(path, b"x")
        assert storage.ensure_local(path) is True

    def test_delete_file_removes_local_and_remote(self, monkeypatch):
        deleted = []

        def handler(request: httpx.Request) -> httpx.Response:
            deleted.append((request.method, request.url.path))
            return httpx.Response(200, json={})

        monkeypatch.setattr(storage, "get_storage", lambda: make_supabase(handler))
        path = settings.certificates_dir / "DEL-1.pdf"
        path.write_bytes(b"x")
        storage.delete_file(path)
        assert not path.exists()
        assert deleted == [("DELETE", f"/storage/v1/object/{BUCKET}/certificates/DEL-1.pdf")]

    def test_delete_prefix_removes_local_tree(self):
        target = settings.uploads_dir / "34"
        target.mkdir(parents=True, exist_ok=True)
        (target / "a.csv").write_bytes(b"a")
        storage.delete_prefix("uploads/34")
        assert not target.exists()

    def test_remote_delete_failures_are_best_effort(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        monkeypatch.setattr(storage, "get_storage", lambda: make_supabase(handler))
        # Neither call should raise: cleanup is best-effort by design.
        storage.delete_file(settings.certificates_dir / "NOPE.pdf")
        storage.delete_prefix("uploads/35")
