"""OIDC discovery, signature, claims, cache, and scope validation."""

import asyncio
import json
import time

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from unifi_mcp.auth.oidc import OIDCTokenVerifier

ISSUER = "https://identity.example.com"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
JWKS_URL = f"{ISSUER}/keys"
AUDIENCE = "unifi-mcp"
PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_JWK = json.loads(RSAAlgorithm.to_jwk(PRIVATE_KEY.public_key())) | {
    "kid": "current",
    "alg": "RS256",
    "use": "sig",
}


def token(**overrides):
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "operator-1",
        "client_id": "mcp-client",
        "scope": "unifi:read unifi:write",
        "iat": now,
        "exp": now + 300,
    }
    claims.update(overrides)
    return jwt.encode(claims, PRIVATE_KEY, algorithm="RS256", headers={"kid": "current"})


@pytest.fixture
async def verifier():
    async with httpx.AsyncClient() as client:
        yield OIDCTokenVerifier(
            issuer=ISSUER,
            audience=AUDIENCE,
            algorithms=["RS256"],
            required_scope="unifi:read",
            client=client,
            cache_ttl_seconds=300,
        )


def mock_metadata():
    respx.get(DISCOVERY_URL).mock(
        return_value=httpx.Response(200, json={"issuer": ISSUER, "jwks_uri": JWKS_URL})
    )
    respx.get(JWKS_URL).mock(return_value=httpx.Response(200, json={"keys": [PUBLIC_JWK]}))


@respx.mock
async def test_valid_token_returns_sdk_access_token(verifier):
    mock_metadata()

    access = await verifier.verify_token(token())

    assert access is not None
    assert access.client_id == "mcp-client"
    assert access.subject == "operator-1"
    assert access.scopes == ["unifi:read", "unifi:write"]
    assert access.claims == {"iss": ISSUER}


@respx.mock
async def test_concurrent_verification_single_flights_discovery_and_jwks(verifier):
    discovery = respx.get(DISCOVERY_URL).mock(
        return_value=httpx.Response(200, json={"issuer": ISSUER, "jwks_uri": JWKS_URL})
    )
    jwks = respx.get(JWKS_URL).mock(return_value=httpx.Response(200, json={"keys": [PUBLIC_JWK]}))

    results = await asyncio.gather(*(verifier.verify_token(token()) for _ in range(20)))

    assert all(result is not None for result in results)
    assert discovery.call_count == 1
    assert jwks.call_count == 1


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://attacker.example.com"},
        {"aud": "other-service"},
        {"exp": int(time.time()) - 1},
        {"scope": "unifi:write"},
        {"scope": {"unifi:read": True}},
    ],
)
@respx.mock
async def test_invalid_issuer_audience_expiry_or_scope_is_rejected(verifier, claims):
    mock_metadata()

    assert await verifier.verify_token(token(**claims)) is None


@respx.mock
async def test_discovery_issuer_mismatch_is_rejected(verifier):
    respx.get(DISCOVERY_URL).mock(
        return_value=httpx.Response(
            200, json={"issuer": "https://other.example.com", "jwks_uri": JWKS_URL}
        )
    )

    assert await verifier.verify_token(token()) is None


@respx.mock
async def test_invalid_signature_is_rejected(verifier):
    mock_metadata()
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    invalid = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "operator",
            "scope": "unifi:read",
            "exp": int(time.time()) + 60,
        },
        other_key,
        algorithm="RS256",
        headers={"kid": "current"},
    )

    assert await verifier.verify_token(invalid) is None


@respx.mock
async def test_unknown_key_forces_only_one_bounded_refresh(verifier):
    respx.get(DISCOVERY_URL).mock(
        return_value=httpx.Response(200, json={"issuer": ISSUER, "jwks_uri": JWKS_URL})
    )
    route = respx.get(JWKS_URL).mock(
        side_effect=[
            httpx.Response(200, json={"keys": []}),
            httpx.Response(200, json={"keys": []}),
        ]
    )

    unknown = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "operator",
            "scope": "unifi:read",
            "exp": int(time.time()) + 60,
        },
        PRIVATE_KEY,
        algorithm="RS256",
        headers={"kid": "unknown"},
    )
    assert await verifier.verify_token(unknown) is None
    assert await verifier.verify_token(unknown) is None
    assert route.call_count == 2


@respx.mock
async def test_same_key_id_rotation_refreshes_once_after_signature_failure(verifier):
    new_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    new_public_jwk = json.loads(RSAAlgorithm.to_jwk(new_private_key.public_key())) | {
        "kid": "current",
        "alg": "RS256",
        "use": "sig",
    }
    respx.get(DISCOVERY_URL).mock(
        return_value=httpx.Response(200, json={"issuer": ISSUER, "jwks_uri": JWKS_URL})
    )
    route = respx.get(JWKS_URL).mock(
        side_effect=[
            httpx.Response(200, json={"keys": [PUBLIC_JWK]}),
            httpx.Response(200, json={"keys": [new_public_jwk]}),
        ]
    )
    rotated = jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": "operator",
            "scope": "unifi:read",
            "exp": int(time.time()) + 60,
        },
        new_private_key,
        algorithm="RS256",
        headers={"kid": "current"},
    )

    assert await verifier.verify_token(rotated) is not None
    assert route.call_count == 2


@respx.mock
async def test_unallowed_token_algorithm_is_rejected_before_discovery(verifier):
    symmetric = jwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "sub": "operator", "exp": int(time.time()) + 60},
        "not-a-real-secret-that-is-at-least-32-bytes",
        algorithm="HS256",
        headers={"kid": "current"},
    )

    assert await verifier.verify_token(symmetric) is None
    assert respx.calls.call_count == 0
