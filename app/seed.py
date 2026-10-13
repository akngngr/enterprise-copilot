"""Seed the default profile document for a visitor's first session.

Why this exists: the corpus starts empty for every new user, so the first
question returns "I couldn't find any relevant documents to answer your
question." That is the worst possible first impression for someone evaluating
the project, and it hides a working RAG pipeline behind what looks like a
broken one.

How it works:
- The seed is ingested through the ordinary PDF pipeline, so it exercises the
  same embedding and storage path a visitor's own upload uses rather than
  bypassing it.
- It is scoped to the visitor's own `owner_id`, exactly like any upload. It
  does not create a shared corpus, and it does not weaken the per-user
  isolation added in `feat: scope documents to the uploading user via OIDC`.
- Once the visitor uploads a PDF of their own, the seed is removed so their
  document stands alone.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ingest import process_pdf
from app.models import Document

SEED_FILENAME = "Akin Gungor - Profile.pdf"
SEED_PATH = Path(__file__).resolve().parent.parent / "seed" / "profile.pdf"

# Textual hook for a knowledge base, not a hard dependency: a missing file
# must not break the app, it must just mean no seed this time.
if not SEED_PATH.exists():  # pragma: no cover - only when the artefact is absent
    SEED_PATH = Path("/app/seed/profile.pdf")


def seed_bytes() -> bytes | None:
    try:
        return SEED_PATH.read_bytes()
    except OSError:
        return None


def has_user_document(db: Session, owner_id: str) -> bool:
    """True when the user has a document that is not the seed."""
    return (
        db.execute(
            select(Document.id).where(
                Document.owner_id == owner_id,
                Document.is_seed.is_(False),
            )
        ).first()
        is not None
    )


def drop_seed(db: Session, owner_id: str) -> int:
    result = db.execute(
        delete(Document).where(Document.owner_id == owner_id, Document.is_seed.is_(True))
    )
    db.commit()
    return int(result.rowcount or 0)


def ensure_seed_document(db: Session, owner_id: str) -> bool:
    """Ingest the seed profile if the user has nothing of their own.

    Returns True when a document was created. Safe to call on every request:
    it is a cheap existence check when a seed is already present, and a no-op
    once the user has uploaded their own PDF.

    Never raises. A seed is a convenience, and failing a visitor's session
    because the convenience failed would be strictly worse than an empty
    corpus.
    """
    try:
        if has_user_document(db, owner_id):
            return False
        if (
            db.execute(
                select(Document.id).where(
                    Document.owner_id == owner_id,
                    Document.is_seed.is_(True),
                )
            ).first()
            is not None
        ):
            return False

        payload = seed_bytes()
        if not payload:
            return False

        process_pdf(
            file_bytes=payload,
            original_filename=SEED_FILENAME,
            owner_id=owner_id,
            content_digest=hashlib.sha256(payload).hexdigest(),
            db=db,
            is_seed=True,
        )
        db.commit()
        return True
    except Exception as error:  # noqa: BLE001 - seeding must never break a session
        db.rollback()
        print(f"[seed] skipped for {owner_id[:12]}…: {type(error).__name__}: {error}")
        return False