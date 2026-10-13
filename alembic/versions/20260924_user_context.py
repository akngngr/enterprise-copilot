import os

from alembic import op
import pgvector.sqlalchemy
import sqlalchemy as sa

revision = "20260924_user_context"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.String(length=255), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("content_digest", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "content_digest",
            "embedding_model",
            name="uq_documents_owner_digest_embedding_model",
        ),
    )
    op.create_index(
        "ix_documents_owner_created_at",
        "documents",
        ["owner_id", "created_at"],
    )

    existing_tables = sa.inspect(op.get_bind()).get_table_names()
    if "document_chunks" in existing_tables:
        op.add_column(
            "document_chunks",
            sa.Column("document_id", sa.Uuid(), nullable=True),
        )
        connection = op.get_bind()
        has_legacy_rows = connection.execute(
            sa.text("SELECT EXISTS (SELECT 1 FROM document_chunks)")
        ).scalar()
        if has_legacy_rows and os.getenv("ALLOW_LEGACY_CONTEXT_DELETE") != "true":
            raise RuntimeError(
                "Legacy document chunks require "
                "ALLOW_LEGACY_CONTEXT_DELETE=true after backup"
            )
        op.execute("DELETE FROM document_chunks")
        op.alter_column(
            "document_chunks",
            "document_id",
            existing_type=sa.Uuid(),
            nullable=False,
        )
        op.alter_column(
            "document_chunks",
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
        op.alter_column(
            "document_chunks",
            "embedding",
            existing_type=pgvector.sqlalchemy.Vector(768),
            nullable=False,
        )
        op.create_foreign_key(
            "fk_document_chunks_document_id_documents",
            "document_chunks",
            "documents",
            ["document_id"],
            ["id"],
            ondelete="CASCADE",
        )
        op.create_unique_constraint(
            "uq_document_chunks_document_index",
            "document_chunks",
            ["document_id", "chunk_index"],
        )
    else:
        op.create_table(
            "document_chunks",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("document_id", sa.Uuid(), nullable=False),
            sa.Column("source_filename", sa.String(length=255), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("embedding", pgvector.sqlalchemy.Vector(768), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["document_id"],
                ["documents.id"],
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "document_id",
                "chunk_index",
                name="uq_document_chunks_document_index",
            ),
        )


def downgrade() -> None:
    op.drop_table("document_chunks")
    op.drop_index("ix_documents_owner_created_at", table_name="documents")
    op.drop_table("documents")
