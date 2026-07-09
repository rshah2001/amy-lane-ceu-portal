"""Shared fixtures for API-level tests.

The FastAPI app runs against an in-memory SQLite database by overriding the
``get_db`` dependency. SQLite needs ``StaticPool`` plus
``check_same_thread=False`` so the TestClient's worker threads all share the
single in-memory connection.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Make `import app` work no matter which directory pytest is launched from.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.models  # noqa: E402,F401 - register every mapper before create_all
from app.core.config import settings  # noqa: E402
from app.core.security import create_access_token, get_password_hash  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.models.user import User  # noqa: E402

TEST_PASSWORD = "CorrectHorse9!"

_unique_counter = itertools.count(1)


def unique_email(prefix: str = "user") -> str:
    """Unique emails keep the login rate limiter (keyed by email + client IP)
    from tripping across tests that intentionally fail a login attempt."""
    return f"{prefix}{next(_unique_counter)}@example.com"


@pytest.fixture(scope="session", autouse=True)
def safe_settings(tmp_path_factory):
    """Redirect file storage into a temp dir and force log-mode email.

    The developer .env configures real SMTP credentials; tests must never
    send actual email or write into the repo's storage directory.
    """
    original_storage = settings.storage_dir
    original_email_mode = settings.email_delivery_mode
    settings.storage_dir = tmp_path_factory.mktemp("storage")
    settings.email_delivery_mode = "log"
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    settings.certificates_dir.mkdir(parents=True, exist_ok=True)
    yield
    settings.storage_dir = original_storage
    settings.email_delivery_mode = original_email_mode


@pytest.fixture(scope="session")
def password_hash() -> str:
    # bcrypt hashing is slow; hash the shared test password once per session.
    return get_password_hash(TEST_PASSWORD)


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False)


@pytest.fixture()
def db_session(session_factory):
    session = session_factory()
    yield session
    session.close()


@pytest.fixture()
def client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    fastapi_app.dependency_overrides[get_db] = override_get_db
    with TestClient(fastapi_app) as test_client:
        yield test_client
    fastapi_app.dependency_overrides.pop(get_db, None)


def make_user(
    db_session,
    password_hash: str,
    *,
    role: str,
    email: str | None = None,
    full_name: str | None = None,
    is_active: bool = True,
) -> SimpleNamespace:
    user = User(
        email=email or unique_email(role),
        full_name=full_name or f"Test {role.title()}",
        role=role,
        hashed_password=password_hash,
        is_active=is_active,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return SimpleNamespace(
        id=user.id,
        email=user.email,
        role=user.role,
        full_name=user.full_name,
        headers={"Authorization": f"Bearer {create_access_token(str(user.id), user.role)}"},
    )


@pytest.fixture()
def admin(db_session, password_hash):
    return make_user(db_session, password_hash, role="admin")


@pytest.fixture()
def presenter(db_session, password_hash):
    return make_user(db_session, password_hash, role="presenter")


@pytest.fixture()
def other_presenter(db_session, password_hash):
    return make_user(db_session, password_hash, role="presenter")
