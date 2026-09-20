"""clerk_to_supabase_auth

Rename the Clerk user-id column to the Supabase one across every table, and
lock the app tables down against Supabase's auto-generated REST API.

The rename
----------
`clerk_user_id` held Clerk's `user_xxx` id; it now holds the UUID of the row in
Supabase's `auth.users`. Both are opaque strings, so the column type does not
change — but the name would otherwise lie about what is in it for the life of
the project.

Existing rows keep their old Clerk ids, which no longer match any Supabase
user. That is deliberate and reversible: nothing is deleted, and an operator
who is re-mapping accounts can do it with an UPDATE afterwards. What must NOT
happen is the data being dropped because the column was renamed.

Row Level Security
------------------
Supabase publishes every table in `public` through PostgREST, reachable with
the anon key that ships in the frontend bundle. Tables created by Alembic have
no RLS policies, and a table with RLS *disabled* is readable and writable by
anyone holding that key — which is everyone. Enabling RLS with no policy is
therefore the fix, not a half-measure: PostgREST's `anon` and `authenticated`
roles are denied everything, while the owner role this API connects as is
unaffected (owners bypass RLS unless FORCE is set).

The grants are revoked as well. RLS alone would be enough, but a future
migration that adds a policy for one case should not silently open the table
for every other one.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3f8a1d47e60"
down_revision: Union[str, None] = "a1c4e7b90f21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


#: Every table carrying the id. `users` leads: on SQLite the child tables are
#: rebuilt with a foreign key spelled out against the *renamed* parent column,
#: so the parent has to have been renamed by the time they are.
TABLES = ("users", "comparisons", "rate_alerts", "provider_clicks")

OLD = "clerk_user_id"
NEW = "supabase_user_id"


def _tables_with(column: str) -> list[str]:
    """
    The tables that actually have this column, in TABLES order.

    A database created by `Base.metadata.create_all` before this migration ran
    already has the new name, and `provider_clicks` does not exist at all on a
    deployment that stopped short of its migration. Renaming blind fails on
    both; checking makes the migration idempotent where it needs to be.
    """
    inspector = sa.inspect(op.get_bind())
    present = set(inspector.get_table_names())
    out = []
    for table in TABLES:
        if table not in present:
            continue
        if column in {c["name"] for c in inspector.get_columns(table)}:
            out.append(table)
    return out


# ── Explicit table definitions for SQLite's copy-and-replace ──────────────────
#
# SQLite cannot ALTER a column, so Alembic's batch mode rebuilds the table from
# a definition of it. Left to reflect the table itself, it would carry over the
# foreign keys pointing at `users.clerk_user_id` — and `users` is renamed in
# this same migration, so the rebuilt children would reference a column that no
# longer exists. Spelling the shape out here is what avoids that: `local` is
# the column name as it is on disk right now (what batch renames), `parent` is
# the name it already has on `users` (what the foreign key must point at).

def _users_table(local: str) -> sa.Table:
    return sa.Table(
        "users",
        sa.MetaData(),
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(local, sa.String, nullable=False),
        sa.Column("email", sa.String),
        sa.Column("full_name", sa.String),
        sa.Column("country", sa.String),
        sa.Column("university", sa.String),
        sa.Column("whatsapp_number", sa.String),
        sa.Column("home_currency", sa.String),
        sa.Column("corridor_from", sa.String),
        sa.Column("corridor_to", sa.String),
        sa.Column("is_onboarded", sa.Boolean),
        sa.Column("created_at", sa.DateTime),
        sa.Column("updated_at", sa.DateTime),
    )


def _child_tables(local: str, parent: str) -> dict[str, sa.Table]:
    metadata = sa.MetaData()
    fk = f"users.{parent}"
    return {
        "comparisons": sa.Table(
            "comparisons", metadata,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(local, sa.String, sa.ForeignKey(fk, ondelete="CASCADE")),
            sa.Column("amount", sa.Float, nullable=False),
            sa.Column("from_currency", sa.String, nullable=False),
            sa.Column("to_currency", sa.String, nullable=False),
            sa.Column("results_json", sa.Text, nullable=False),
            sa.Column("created_at", sa.DateTime),
        ),
        "rate_alerts": sa.Table(
            "rate_alerts", metadata,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(local, sa.String, sa.ForeignKey(fk, ondelete="CASCADE"),
                      nullable=False),
            sa.Column("from_currency", sa.String, nullable=False),
            sa.Column("to_currency", sa.String, nullable=False),
            sa.Column("amount", sa.Float, nullable=False),
            sa.Column("target_rate", sa.Float, nullable=False),
            sa.Column("provider", sa.String),
            sa.Column("pay_out_method", sa.String),
            sa.Column("notify_email", sa.Boolean),
            sa.Column("notify_whatsapp", sa.Boolean),
            sa.Column("is_active", sa.Boolean),
            sa.Column("last_triggered", sa.DateTime),
            sa.Column("created_at", sa.DateTime),
        ),
        "provider_clicks": sa.Table(
            "provider_clicks", metadata,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(local, sa.String),
            sa.Column("provider", sa.String, nullable=False),
            sa.Column("from_currency", sa.String, nullable=False),
            sa.Column("to_currency", sa.String, nullable=False),
            sa.Column("amount", sa.Float, nullable=False),
            sa.Column("created_at", sa.DateTime),
        ),
    }


def _rename(old: str, new: str) -> None:
    bind = op.get_bind()
    targets = _tables_with(old)
    if not targets:
        return

    if bind.dialect.name == "postgresql":
        for table in targets:
            op.execute(f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}"')
        # Postgres keeps foreign-key constraints pointing at a renamed column
        # automatically; only the index name has to be brought along.
        op.execute(f"ALTER INDEX IF EXISTS ix_users_{old} RENAME TO ix_users_{new}")
        return

    # SQLite (local development and the test suite). `users` first — see TABLES.
    children = _child_tables(old, new)
    for table in targets:
        if table == "users":
            op.drop_index(f"ix_users_{old}", table_name="users")
            with op.batch_alter_table("users", copy_from=_users_table(old)) as batch:
                batch.alter_column(old, new_column_name=new)
            op.create_index(f"ix_users_{new}", "users", [new], unique=True)
        else:
            with op.batch_alter_table(table, copy_from=children[table]) as batch:
                batch.alter_column(old, new_column_name=new)


def _lock_down_public_tables(enable: bool) -> None:
    """
    Enable or disable RLS on the app's tables. PostgreSQL / Supabase only.

    `anon` and `authenticated` are Supabase's own roles and do not exist on a
    plain Postgres, so the grants are only touched when they are there.
    """
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    inspector = sa.inspect(bind)
    present = set(inspector.get_table_names())
    verb = "ENABLE" if enable else "DISABLE"

    for table in TABLES:
        if table not in present:
            continue
        op.execute(f'ALTER TABLE "{table}" {verb} ROW LEVEL SECURITY')
        grant = "GRANT ALL" if not enable else "REVOKE ALL"
        direction = "TO" if not enable else "FROM"
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
                    {grant} ON TABLE public."{table}" {direction} anon;
                END IF;
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
                    {grant} ON TABLE public."{table}" {direction} authenticated;
                END IF;
            END $$;
            """
        )


def upgrade() -> None:
    _rename(OLD, NEW)
    _lock_down_public_tables(enable=True)


def downgrade() -> None:
    _lock_down_public_tables(enable=False)
    _rename(NEW, OLD)
