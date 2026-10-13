import os
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse

import jwt
import requests
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError, PyJWKClientError

OIDC_ISSUER = os.getenv("OIDC_ISSUER", "").strip()
OIDC_AUDIENCE = os.getenv("OIDC_AUDIENCE", "").strip()
OIDC_JWKS_URL = os.getenv("OIDC_JWKS_URL", "").strip()
OIDC_ALGORITHMS = tuple(
    algorithm.strip()
    for algorithm in os.getenv("OIDC_ALGORITHMS", "RS256").split(",")
    if algorithm.strip()
)
ALLOWED_OIDC_ALGORITHMS = {
    "RS256",
    "RS384",
    "RS512",
    "PS256",
    "PS384",
    "PS512",
    "ES256",
    "ES384",
    "ES512",
    "EdDSA",
}

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class CurrentUser:
    id: str


class OIDCConfigurationError(RuntimeError):
    pass


def require_secure_url(value: str, setting_name: str) -> None:
    parsed = urlparse(value)
    local_http = parsed.hostname in {"localhost", "127.0.0.1", "::1"} and parsed.scheme == "http"
    if not parsed.hostname or (parsed.scheme != "https" and not local_http):
        raise OIDCConfigurationError(f"{setting_name} must use HTTPS outside local development")


@lru_cache
def get_jwk_client() -> PyJWKClient:
    if not OIDC_ISSUER or not OIDC_AUDIENCE:
        raise OIDCConfigurationError("OIDC_ISSUER and OIDC_AUDIENCE must be configured")
    if not OIDC_ALGORITHMS or not set(OIDC_ALGORITHMS).issubset(ALLOWED_OIDC_ALGORITHMS):
        raise OIDCConfigurationError("OIDC_ALGORITHMS contains a disallowed algorithm")
    require_secure_url(OIDC_ISSUER, "OIDC_ISSUER")

    jwks_url = OIDC_JWKS_URL
    if not jwks_url:
        discovery_url = f"{OIDC_ISSUER.rstrip('/')}/.well-known/openid-configuration"
        response = requests.get(discovery_url, timeout=5, allow_redirects=False)
        response.raise_for_status()
        metadata = response.json()
        if not isinstance(metadata, dict) or metadata.get("issuer") != OIDC_ISSUER:
            raise OIDCConfigurationError("OIDC discovery metadata issuer does not match OIDC_ISSUER")
        jwks_url = metadata.get("jwks_uri")
        if not isinstance(jwks_url, str) or not jwks_url:
            raise OIDCConfigurationError("OIDC discovery metadata does not contain jwks_uri")

    require_secure_url(jwks_url, "OIDC_JWKS_URL")
    return PyJWKClient(jwks_url, cache_keys=True, lifespan=300, timeout=5)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if len(credentials.credentials) > 16_384:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        client = get_jwk_client()
    except (OIDCConfigurationError, requests.RequestException, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OIDC authentication is not configured",
        ) from error

    try:
        token_header = jwt.get_unverified_header(credentials.credentials)
        key_id = token_header.get("kid")
        if key_id is not None and (not isinstance(key_id, str) or not 1 <= len(key_id) <= 128):
            raise InvalidTokenError("Invalid key identifier")
        signing_key = client.get_signing_key_from_jwt(credentials.credentials)
        claims = jwt.decode(
            credentials.credentials,
            signing_key.key,
            algorithms=list(OIDC_ALGORITHMS),
            audience=OIDC_AUDIENCE,
            issuer=OIDC_ISSUER,
            options={
                "require": ["aud", "exp", "iat", "iss", "sub"],
                "strict_aud": True,
            },
        )
    except (InvalidTokenError, PyJWKClientError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error

    token_audience = claims.get("aud")
    authorized_party = claims.get("azp")
    if isinstance(token_audience, list):
        authorized_party_matches = authorized_party == OIDC_AUDIENCE
    else:
        authorized_party_matches = authorized_party is None or authorized_party == token_audience
    if not authorized_party_matches:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is not authorized for this application",
            headers={"WWW-Authenticate": "Bearer"},
        )

    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject or len(subject) > 255:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token does not contain a valid subject",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return CurrentUser(id=subject)
