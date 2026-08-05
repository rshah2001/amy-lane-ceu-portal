"""Fail if the Alembic migration chain and the ORM models disagree.

The test suite builds its schema with ``Base.metadata.create_all`` against
SQLite, but production is migration-only Postgres. Nothing compared the two, so
a column could be added to a model and never to a migration (or vice versa) and
every test would still pass. That is exactly how ``notifications.created_at``
came to be NOT NULL in the ORM and nullable in migration 0006.

This script upgrades a real Postgres database to head and then asks Alembic to
diff the resulting schema against the model metadata. Any difference is drift,
and drift means the schema developers test against is not the schema users get.

Usage:
    DATABASE_URL=postgresql+psycopg://... python -m scripts.check_migration_drift
"""

from __future__ import annotations

import sys

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app.core.config import settings
from app.db.base import Base

# Autogenerate operation names to ignore. Empty today because the chain is
# genuinely clean; if a future Postgres/Alembic pairing starts reporting
# cosmetic churn (implicit indexes behind unique constraints are the usual
# culprit), add the operation name here rather than weakening the check.
IGNORED_OPERATIONS: frozenset[str] = frozenset()


def _describe(diff: object) -> str:
    """Render one autogenerate diff entry as a single readable line."""
    if isinstance(diff, tuple) and diff:
        operation = diff[0]
        details = ", ".join(
            getattr(part, "name", None) or str(part) for part in diff[1:] if part is not None
        )
        return f"{operation}: {details}"
    return str(diff)


def main() -> int:
    # Import every model module for its side effect of registering tables on
    # Base.metadata; without this the comparison sees an empty model schema and
    # reports every table as "should be dropped".
    import app.models  # noqa: F401

    engine = create_engine(settings.database_url)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        diffs = [
            diff
            for diff in compare_metadata(context, Base.metadata)
            if not (isinstance(diff, tuple) and diff and diff[0] in IGNORED_OPERATIONS)
        ]

    if not diffs:
        print("No drift: the migration chain matches the ORM models.")
        return 0

    print(f"Schema drift detected ({len(diffs)} difference(s)) between migrations and models:\n")
    for diff in diffs:
        # A nested list is autogenerate's grouping for per-column changes.
        if isinstance(diff, list):
            for inner in diff:
                print(f"  - {_describe(inner)}")
        else:
            print(f"  - {_describe(diff)}")
    print(
        "\nAdd a migration so the deployed schema matches the models, "
        "or correct the model if the migration is right."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
