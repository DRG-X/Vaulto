"""
database.py — the connection to Supabase Postgres.

Which connection string to use
------------------------------
Supabase offers three, and the difference is not cosmetic:

  * **Transaction pooler** (port 6543) — what a stateless API server should
    use. Every statement may land on a different backend, so server-side
    prepared statements and session-scoped state do not survive. SQLAlchemy's
    psycopg2 driver does not use server-side prepares, so it is safe here.
  * **Session pooler / direct** (port 5432) — one backend per connection.
    Required for schema migrations, which run in a transaction and rely on
    session state.
  * **Direct** — IPv6-only on Supabase unless the IPv4 add-on is enabled,
    which is why the poolers are the default advice.

`DATABASE_URL` is the one the app serves requests on; `DIRECT_URL` is the
optional session-mode URL Alembic uses instead when it is set (see
alembic/env.py). With only `DATABASE_URL` set, both use it and everything
still works — the split exists so a deployment on the transaction pooler can
still migrate.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./flint.db")


def normalize_url(url: str) -> str:
    """
    Make a pasted connection string something SQLAlchemy accepts.

    Supabase hands out `postgresql://…`, but `postgres://` is still what several
    dashboards and older tooling copy, and SQLAlchemy 2 rejects that scheme
    outright rather than guessing.
    """
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


DATABASE_URL = normalize_url(DATABASE_URL)

is_sqlite = DATABASE_URL.startswith("sqlite")

if is_sqlite:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        DATABASE_URL,
        # A pooled Supabase connection is closed from the far end after a
        # period of idleness, and the first query on a dead one fails with
        # "server closed the connection unexpectedly". pre_ping spends one
        # cheap round trip to find that out and reconnect instead.
        pool_pre_ping=True,
        # Stay well under the pooler's own idle timeout so we retire
        # connections before it does.
        pool_recycle=300,
        # Supabase counts connections per project across every client. A small
        # pool from each app instance leaves headroom for migrations, the SQL
        # editor, and the poolers themselves.
        pool_size=5,
        max_overflow=5,
        connect_args={
            # Supabase terminates TLS at the pooler and refuses plaintext; being
            # explicit means a URL pasted without ?sslmode= still connects.
            "sslmode": os.getenv("PGSSLMODE", "require"),
            "application_name": "vaulto-api",
        },
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
