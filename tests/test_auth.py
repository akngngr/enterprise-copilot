from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient

from app import auth
from app.auth import get_current_user
from app.main import app


def make_token(
    private_key,
    subject="user-a",
    audience="copilot-api",
    authorized_party=None,
):
    now = datetime.now(timezone.utc)
    claims = {
        "iss": "https://identity.example.com",
        "aud": audience,
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    if authorized_party is not None:
        claims["azp"] = authorized_party
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


def test_valid_token_resolves_subject(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = make_token(private_key)
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

    user = get_current_user(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    )

    assert user.id == "user-a"


def test_wrong_audience_is_rejected(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = make_token(private_key, audience="another-api")
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

    with pytest.raises(HTTPException) as error:
        get_current_user(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        )

    assert error.value.status_code == 401


def test_wrong_authorized_party_is_rejected(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = make_token(
        private_key,
        audience=["copilot-api", "another-api"],
        authorized_party="another-client",
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

    with pytest.raises(HTTPException) as error:
        get_current_user(
            HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        )

    assert error.value.status_code == 401


def test_insecure_remote_oidc_url_is_rejected():
    with pytest.raises(auth.OIDCConfigurationError):
        auth.require_secure_url("http://identity.example.com", "OIDC_ISSUER")


def test_missing_bearer_token_is_rejected():
    with pytest.raises(HTTPException) as error:
        get_current_user(None)

    assert error.value.status_code == 401


def test_document_api_requires_authentication():
    with TestClient(app) as client:
        response = client.get("/documents/")

    assert response.status_code == 401
