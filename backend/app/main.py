import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # noqa: F401
from app.api import (
    auth,
    certificates,
    compliance,
    distribution,
    events,
    notifications,
    reports,
    settings as settings_api,
    surveys,
    system,
    tests,
    uploads,
    users,
    verification,
)
from app.core.config import settings

# Uvicorn only wires up its own loggers; give application loggers (e.g. the
# log-mode emailer) a console handler so their output is visible.
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="REST API for CEU event compliance, approvals, certificates, and audit reporting.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(events.router, prefix="/api")
app.include_router(uploads.router, prefix="/api")
app.include_router(compliance.router, prefix="/api")
app.include_router(certificates.router, prefix="/api")
app.include_router(reports.router, prefix="/api")
app.include_router(settings_api.router, prefix="/api")
app.include_router(surveys.router, prefix="/api")
app.include_router(tests.router, prefix="/api")
app.include_router(distribution.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(verification.router, prefix="/api")
app.include_router(system.router, prefix="/api")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}
