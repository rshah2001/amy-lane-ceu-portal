"""Shared column types.

``JSON`` here is the plain SQLAlchemy JSON type with a Postgres variant of
JSONB. Every JSON column in this schema was created as ``jsonb`` (see migration
0001 onwards), so declaring bare ``sa.JSON`` in the models left the ORM
permanently out of step with the database: ``alembic revision --autogenerate``
emitted a ``jsonb -> json`` alter for each of them, and applying one of those by
accident would rewrite a live table into the weaker type. Behaviour on SQLite
(the test database, which has no JSONB) is unchanged.
"""
from sqlalchemy import JSON as _JSON
from sqlalchemy import Text
from sqlalchemy.dialects import postgresql

JSON = _JSON().with_variant(postgresql.JSONB(astext_type=Text()), "postgresql")
