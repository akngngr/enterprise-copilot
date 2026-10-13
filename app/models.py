import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "content_digest",
            "embedding_model",
            name="uq_documents_owner_digest_embedding_model",
        ),
        Index("ix_documents_owner_created_at", "owner_id", "created_at"),
    )

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(String(255), nullable=False)
    source_filename = Column(String(255), nullable=False)
    content_digest = Column(String(64), nullable=False)
    embedding_model = Column(String(100), nullable=False)
    # Marks the default profile document that is seeded for a visitor's first
    # session. It is removed as soon as the visitor uploads a PDF of their own.
    is_seed = Column(Boolean, nullable=False, server_default=text("false"), default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    chunks = relationship(
        "DocumentChunk",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_document_chunks_document_index"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(
        Uuid(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_filename = Column(String(255), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(768), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    document = relationship("Document", back_populates="chunks")
