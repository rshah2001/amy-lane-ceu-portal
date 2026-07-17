"""File storage abstraction: Supabase Storage with local disk fallback.

All uploaded documents (rosters, sign-in sheets, post-tests, surveys,
certificate templates) and generated certificate PDFs go through this module.

Two backends:

- ``SupabaseStorage`` — used when ``SUPABASE_URL``, ``SUPABASE_SERVICE_ROLE_KEY``
  and ``SUPABASE_STORAGE_BUCKET`` are all configured. Talks to the Supabase
  Storage REST API over httpx using the service-role key. The bucket MUST be
  created as **private**: it holds attendee PII and certificates (protected
  info under the compliance requirements), and files are only ever served
  through this API's authenticated endpoints — never via public bucket URLs.
- ``LocalStorage`` — the previous behavior (plain files under
  ``settings.storage_dir``), used when the Supabase settings are absent.
  This is the development fallback.

Object keys mirror the on-disk layout relative to ``settings.storage_dir``,
e.g. ``uploads/<event_id>/<filename>`` and ``certificates/<number>.pdf``, so
``storage_path``/``pdf_path`` values already stored in the database map onto
keys directly.

When Supabase is configured the local disk still acts as a write-through
cache: consumers such as ``FileResponse``, ReportLab and the email attachment
code operate on paths, and ``ensure_local`` re-materializes a missing file
from the bucket (e.g. after an ephemeral-disk restart).
"""
from __future__ import annotations

import logging
import shutil
from functools import lru_cache
from pathlib import Path

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_LIST_PAGE_SIZE = 100
_DELETE_BATCH_SIZE = 100


class StorageError(RuntimeError):
    """A storage backend operation failed (network, auth, or server error)."""


class LocalStorage:
    """Plain files under a root directory (the historical behavior)."""

    is_remote = False

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / key

    def save(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise FileNotFoundError(key)
        return path.read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> None:
        shutil.rmtree(self._path(prefix), ignore_errors=True)


class SupabaseStorage:
    """Supabase Storage over its REST API (private bucket, service-role auth)."""

    is_remote = True

    def __init__(
        self,
        url: str,
        service_role_key: str,
        bucket: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.bucket = bucket
        self._client = httpx.Client(
            base_url=url.rstrip("/") + "/storage/v1",
            headers={
                "Authorization": f"Bearer {service_role_key}",
                "apikey": service_role_key,
            },
            timeout=30.0,
            transport=transport,
        )

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            return self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise StorageError(f"Supabase Storage request failed: {exc}") from exc

    def save(self, key: str, data: bytes) -> None:
        response = self._request(
            "POST",
            f"/object/{self.bucket}/{key}",
            content=data,
            headers={"Content-Type": "application/octet-stream", "x-upsert": "true"},
        )
        if response.is_error:
            raise StorageError(
                f"Supabase upload of {key!r} failed: {response.status_code} {response.text[:300]}"
            )

    def read(self, key: str) -> bytes:
        response = self._request("GET", f"/object/{self.bucket}/{key}")
        if response.status_code == 404:
            raise FileNotFoundError(key)
        if response.is_error:
            raise StorageError(
                f"Supabase download of {key!r} failed: {response.status_code} {response.text[:300]}"
            )
        return response.content

    def delete(self, key: str) -> None:
        response = self._request("DELETE", f"/object/{self.bucket}/{key}")
        if response.is_error and response.status_code != 404:
            raise StorageError(
                f"Supabase delete of {key!r} failed: {response.status_code} {response.text[:300]}"
            )

    def _list_keys(self, prefix: str) -> list[str]:
        """All object keys under a prefix, recursing into sub-folders."""
        keys: list[str] = []
        folders: list[str] = []
        offset = 0
        while True:
            response = self._request(
                "POST",
                f"/object/list/{self.bucket}",
                json={"prefix": prefix, "limit": _LIST_PAGE_SIZE, "offset": offset},
            )
            if response.is_error:
                raise StorageError(
                    f"Supabase list of {prefix!r} failed: {response.status_code} {response.text[:300]}"
                )
            entries = response.json()
            for entry in entries:
                name = f"{prefix.rstrip('/')}/{entry['name']}" if prefix else entry["name"]
                # Folder placeholders come back without an object id.
                if entry.get("id") is None:
                    folders.append(name)
                else:
                    keys.append(name)
            if len(entries) < _LIST_PAGE_SIZE:
                break
            offset += len(entries)
        for folder in folders:
            keys.extend(self._list_keys(folder))
        return keys

    def delete_prefix(self, prefix: str) -> None:
        keys = self._list_keys(prefix)
        for start in range(0, len(keys), _DELETE_BATCH_SIZE):
            batch = keys[start : start + _DELETE_BATCH_SIZE]
            response = self._request(
                "DELETE", f"/object/{self.bucket}", json={"prefixes": batch}
            )
            if response.is_error:
                raise StorageError(
                    f"Supabase bulk delete under {prefix!r} failed: "
                    f"{response.status_code} {response.text[:300]}"
                )


@lru_cache(maxsize=4)
def _supabase_backend(url: str, service_role_key: str, bucket: str) -> SupabaseStorage:
    # Cached so the httpx connection pool is reused across requests.
    return SupabaseStorage(url, service_role_key, bucket)


def get_storage() -> LocalStorage | SupabaseStorage:
    """The configured backend. Supabase when fully configured, else local disk."""
    if (
        settings.supabase_url
        and settings.supabase_service_role_key
        and settings.supabase_storage_bucket
    ):
        return _supabase_backend(
            settings.supabase_url,
            settings.supabase_service_role_key,
            settings.supabase_storage_bucket,
        )
    # Root is looked up per call: tests redirect settings.storage_dir.
    return LocalStorage(settings.storage_dir)


def file_key(path: Path) -> str:
    """Map a storage path (as stored in the DB) to a backend object key."""
    path = Path(path)
    root = Path(settings.storage_dir)
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        try:
            return path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError as exc:
            raise StorageError(f"{path} is outside the storage root {root}") from exc


def save_bytes(destination: Path, contents: bytes) -> None:
    """Persist bytes at a storage path (writes a local cache copy too when remote)."""
    backend = get_storage()
    backend.save(file_key(destination), contents)
    if backend.is_remote:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(contents)


def mirror_file(path: Path) -> None:
    """Copy an already-written local file (e.g. a generated PDF) to the remote
    backend. No-op for local storage; best-effort — the local copy plus the
    regenerate-on-demand logic keep working if the upload fails."""
    backend = get_storage()
    if not backend.is_remote:
        return
    try:
        backend.save(file_key(path), Path(path).read_bytes())
    except (OSError, StorageError) as exc:
        logger.warning("Could not mirror %s to Supabase Storage: %s", path, exc)


def ensure_local(path: Path) -> bool:
    """True if the file exists locally, fetching it from the remote backend if
    needed (ephemeral-disk recovery). False when it exists nowhere."""
    path = Path(path)
    if path.is_file():
        return True
    backend = get_storage()
    if not backend.is_remote:
        return False
    try:
        data = backend.read(file_key(path))
    except FileNotFoundError:
        return False
    except StorageError as exc:
        logger.warning("Could not fetch %s from Supabase Storage: %s", path, exc)
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return True


def delete_file(path: Path) -> None:
    """Best-effort delete of a single file, locally and remotely."""
    Path(path).unlink(missing_ok=True)
    backend = get_storage()
    if backend.is_remote:
        try:
            backend.delete(file_key(path))
        except StorageError as exc:
            logger.warning("Could not delete %s from Supabase Storage: %s", path, exc)


def delete_prefix(key_prefix: str) -> None:
    """Best-effort delete of everything under a key prefix (e.g. an event's
    uploads folder), locally and remotely."""
    shutil.rmtree(Path(settings.storage_dir) / key_prefix, ignore_errors=True)
    backend = get_storage()
    if backend.is_remote:
        try:
            backend.delete_prefix(key_prefix)
        except StorageError as exc:
            logger.warning(
                "Could not delete prefix %s from Supabase Storage: %s", key_prefix, exc
            )
