import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, inspect, select, text

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is required for database tests",
)

from app.database import Base
from app.models import DocumentChunk


def reset_database(engine):
    Base.metadata.drop_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
        connection.execute(text("DROP TABLE IF EXISTS document_chunks"))
        connection.execute(text("DROP TABLE IF EXISTS documents"))


def create_legacy_chunks(engine):
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE document_chunks (
                    id SERIAL PRIMARY KEY,
                    source_filename VARCHAR(255) NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    embedding VECTOR(768),
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO document_chunks (
                    source_filename,
                    chunk_index,
                    content,
                    embedding
                ) VALUES (
                    'legacy.pdf',
                    0,
                    'legacy content',
                    NULL
                )
                """
            )
        )


def cleanup_database(engine):
    reset_database(engine)


def test_fresh_migration_is_idempotent(test_engine):
    reset_database(test_engine)

    command.upgrade(Config("alembic.ini"), "head")
    command.upgrade(Config("alembic.ini"), "head")

    with test_engine.connect() as connection:
        inspector = inspect(connection)
        document_columns = {
            column["name"]: column for column in inspector.get_columns("documents")
        }
        chunk_columns = {
            column["name"]: column for column in inspector.get_columns("document_chunks")
        }
        foreign_keys = inspector.get_foreign_keys("document_chunks")
        assert "embedding_model" in document_columns
        assert chunk_columns["document_id"]["nullable"] is False
        assert chunk_columns["embedding"]["nullable"] is False
        assert foreign_keys[0]["options"]["ondelete"] == "CASCADE"

    cleanup_database(test_engine)


def test_legacy_migration_requires_explicit_approval(test_engine, monkeypatch):
    reset_database(test_engine)
    create_legacy_chunks(test_engine)
    monkeypatch.delenv("ALLOW_LEGACY_CONTEXT_DELETE", raising=False)

    with pytest.raises(RuntimeError, match="ALLOW_LEGACY_CONTEXT_DELETE=true"):
        command.upgrade(Config("alembic.ini"), "head")

    with test_engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(DocumentChunk.__table__)
        ) == 1
        assert "documents" not in inspect(connection).get_table_names()

    cleanup_database(test_engine)


def test_approved_legacy_migration_removes_unowned_chunks(
    test_engine,
    monkeypatch,
):
    reset_database(test_engine)
    create_legacy_chunks(test_engine)
    monkeypatch.setenv("ALLOW_LEGACY_CONTEXT_DELETE", "true")

    command.upgrade(Config("alembic.ini"), "head")

    with test_engine.connect() as connection:
        assert "documents" in inspect(connection).get_table_names()
        assert connection.scalar(
            select(func.count()).select_from(DocumentChunk.__table__)
        ) == 0

    cleanup_database(test_engine)
