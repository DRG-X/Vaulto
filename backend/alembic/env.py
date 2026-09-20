import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Make sure the backend package root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Override sqlalchemy.url from the environment.
#
# DIRECT_URL wins when it is set. Supabase's transaction pooler (port 6543)
# hands each statement to whichever backend is free, which is right for a
# stateless API and wrong for a migration: DDL here runs inside one
# transaction and relies on session state. DIRECT_URL is the session-mode or
# direct connection string to run migrations over. With only DATABASE_URL set,
# that is what is used and everything still works.
_db_url = os.getenv("DIRECT_URL") or os.getenv("DATABASE_URL", "sqlite:///./flint.db")
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql://", 1)
# Escaped because Alembic runs the value through ConfigParser interpolation,
# where a literal % in a URL-encoded password would otherwise blow up.
config.set_main_option("sqlalchemy.url", _db_url.replace("%", "%%"))

# Interpret the config file for Python logging — but ONLY when Alembic is being
# run as a command-line tool.
#
# `init_schema()` in main.py also loads this env.py, in-process, on every
# startup, and there `fileConfig` is actively harmful: it resets the root logger
# to the ini's `level = WARN` and swaps its handler, so the API logged its
# migrations and then went quiet for the rest of its life — no request log, no
# alert-checker output, no INFO diagnostics. Nothing looked broken, which is
# what made it expensive.
#
# main.py therefore sets `configure_logger = False` (Alembic's own convention for
# this) and keeps the logging it set up. Alembic's "Running upgrade …" lines are
# not lost: the `alembic` logger propagates to that handler instead.
#
# disable_existing_loggers=False covers the CLI path, where the app's loggers may
# also already exist — silencing them is never what is wanted.
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# add your model's MetaData object here
# for 'autogenerate' support
from database import Base  # noqa: E402
from models import User, Comparison, RateAlert, ProviderClick  # noqa: E402, F401
target_metadata = Base.metadata

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # required for SQLite ALTER support
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # required for SQLite ALTER support
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
