import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import func, select

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is required for database tests",
)

from app import auth, ingest, main
from app.auth import CurrentUser, get_current_user
from app.database import Base, SessionLocal
from app.models import Document, DocumentChunk


@pytest.fixture
def clean_database(test_engine):
    Base.metadata.drop_all(test_engine)
    Base.metadata.create_all(test_engine)
    yield
    Base.metadata.drop_all(test_engine)


@pytest.fixture
def api_client():
    principal = {"id": "user-a"}

    def override_user():
        return CurrentUser(id=principal["id"])

    main.app.dependency_overrides[get_current_user] = override_user
    with TestClient(main.app) as client:
        yield client, principal
    main.app.dependency_overrides.clear()


def add_document(owner_id, filename, digest, content, vector):
    with SessionLocal() as db:
        document = Document(
            owner_id=owner_id,
            source_filename=filename,
            content_digest=digest,
            embedding_model="test-model",
        )
        db.add(document)
        db.flush()
        db.add(
            DocumentChunk(
                document_id=document.id,
                source_filename=filename,
                chunk_index=0,
                content=content,
                embedding=vector,
            )
        )
        db.commit()
        return document.id


def test_ingestion_is_idempotent_per_user(clean_database, api_client, monkeypatch):
    class FakePage:
        def extract_text(self):
            return "Private user context"

    class FakeReader:
        pages = [FakePage()]

    monkeypatch.setattr(
        ingest,
        "PdfReader",
        lambda stream, strict: FakeReader(),
    )
    monkeypatch.setattr(
        ingest,
        "get_embedding",
        lambda text: ([1.0] + [0.0] * 767, "test-model"),
    )
    client, principal = api_client
    files = {"file": ("private.pdf", b"same-pdf-bytes", "application/pdf")}

    first = client.post("/ingest/", files=files)
    second = client.post("/ingest/", files=files)
    principal["id"] = "user-b"
    other_user = client.post("/ingest/", files=files)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert other_user.status_code == 200
    assert other_user.json()["id"] != first.json()["id"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Document)) == 2
        assert db.scalar(select(func.count()).select_from(DocumentChunk)) == 2


def test_search_and_ask_only_use_current_users_documents(
    clean_database,
    api_client,
    monkeypatch,
):
    user_a_vector = [1.0] + [0.0] * 767
    user_b_vector = [0.0, 1.0] + [0.0] * 766
    add_document("user-a", "a.pdf", "digest-a", "alpha context", user_a_vector)
    user_b_document = add_document(
        "user-b",
        "b.pdf",
        "digest-b",
        "beta context",
        user_b_vector,
    )
    monkeypatch.setattr(
        main,
        "get_embedding",
        lambda text: (user_a_vector, "test-model"),
    )
    monkeypatch.setattr(main, "query_gemini", lambda prompt: "grounded answer")
    client, principal = api_client

    user_a_results = client.post("/search/", params={"query": "context"})
    principal["id"] = "user-b"
    user_b_results = client.post("/search/", params={"query": "context"})
    user_b_answer = client.post(
        "/ask/",
        json={"question": "What is my context?", "history": []},
    )

    assert [result["source_filename"] for result in user_a_results.json()] == ["a.pdf"]
    assert [result["source_filename"] for result in user_b_results.json()] == ["b.pdf"]
    assert [source["source_filename"] for source in user_b_answer.json()["sources"]] == [
        "b.pdf"
    ]
    assert user_b_answer.json()["answer"] == "grounded answer"
    with SessionLocal() as db:
        assert db.get(Document, user_b_document) is not None


def test_delete_and_clear_are_owner_scoped_and_cascade(
    clean_database,
    api_client,
):
    vector = [1.0] + [0.0] * 767
    user_a_document = add_document("user-a", "a.pdf", "digest-a", "alpha", vector)
    user_b_document = add_document("user-b", "b.pdf", "digest-b", "beta", vector)
    client, principal = api_client

    assert client.delete(f"/documents/{user_b_document}").status_code == 404
    principal["id"] = "user-b"
    assert client.delete(f"/documents/{user_a_document}").status_code == 404
    assert client.delete(f"/documents/{user_b_document}").status_code == 204

    with SessionLocal() as db:
        assert db.get(Document, user_b_document) is None
        assert (
            db.scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .where(DocumentChunk.document_id == user_b_document)
            )
            == 0
        )
        assert db.get(Document, user_a_document) is not None

    clear_response = client.delete("/documents/")
    assert clear_response.status_code == 200
    assert clear_response.json()["documents_deleted"] == 0

    principal["id"] = "user-a"
    clear_response = client.delete("/documents/")
    assert clear_response.json()["documents_deleted"] == 1
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Document)) == 0
        assert db.scalar(select(func.count()).select_from(DocumentChunk)) == 0


def test_api_accepts_valid_signed_oidc_token(clean_database, monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "iss": "https://identity.example.com",
            "aud": "copilot-api",
            "sub": "verified-user",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    document_id = add_document(
        "verified-user",
        "verified.pdf",
        "verified-digest",
        "verified context",
        [1.0] + [0.0] * 767,
    )
    monkeypatch.setattr(auth, "OIDC_ISSUER", "https://identity.example.com")
    monkeypatch.setattr(auth, "OIDC_AUDIENCE", "copilot-api")
    monkeypatch.setattr(auth, "OIDC_ALGORITHMS", ("RS256",))
    monkeypatch.setattr(
        auth,
        "get_jwk_client",
        lambda: SimpleNamespace(
            get_signing_key_from_jwt=lambda encoded: SimpleNamespace(
                key=private_key.public_key()
            )
        ),
    )
    main.app.dependency_overrides.clear()

    with TestClient(main.app) as client:
        response = client.get(
            "/documents/",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert [document["id"] for document in response.json()] == [str(document_id)]
