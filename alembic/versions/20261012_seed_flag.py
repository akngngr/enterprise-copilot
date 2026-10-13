"""Mark the default profile document with is_seed.

The seed document is ingested for a visitor's first session so the copilot can
answer something immediately instead of reporting an empty corpus, and is
removed once that visitor uploads a PDF of their own.

Additive and safe on a live database: a new column with a NOT NULL server
default of false rewrites nothing that already exists, and every row currently
in the table is a real upload.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261012_seed_flag"
down_revision = "20260924_user_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "is_seed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    # Drop the server default so the value is always explicit from the
    # application. Keeping it would silently stamp false on any future insert
    # that omits the column.
    op.alter_column("documents", "is_seed", server_default=None)


def downgrade() -> None:
    op.drop_column("documents", "is_seed")