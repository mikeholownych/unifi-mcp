"""Locally validating OIDC bearer-token verifier with bounded metadata caches."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import urlparse

import httpx
import jwt
from mcp.server.auth.provider import AccessToken

_MAX_METADATA_BYTES = 1_048_576


class OIDCTokenVerifier:
    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        algorithms: list[str],
        required_scope: str,
        client: httpx.AsyncClient | None = None,
        cache_ttl_seconds: float = 300,
        timeout_seconds: float = 10,
    ) -> None:
        self._issuer = issuer.rstrip("/")
        self._audience = audience
        self._algorithms = algorithms
        self._required_scope = required_scope
        self._client = client
        self._cache_ttl_seconds = cache_ttl_seconds
        self._timeout_seconds = timeout_seconds
        self._discovery: tuple[float, dict[str, Any]] | None = None
        self._jwks: tuple[float, dict[str, Any]] | None = None
        self._discovery_lock = asyncio.Lock()
        self._jwks_lock = asyncio.Lock()
        self._last_forced_refresh = float("-inf")
        self._refresh_cooldown_seconds = min(cache_ttl_seconds, 60.0)

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            header = jwt.get_unverified_header(token)
            algorithm = header.get("alg")
            key_id = header.get("kid")
            if algorithm not in self._algorithms or not isinstance(key_id, str) or not key_id:
                return None

            discovery = await self._get_discovery()
            jwks_uri = discovery["jwks_uri"]
            jwk = await self._find_key(jwks_uri, key_id, force=False)
            if jwk is None:
                jwk = await self._find_key(jwks_uri, key_id, force=True)
            if jwk is None or jwk.get("alg") not in {None, algorithm}:
                return None
            if jwk.get("use") not in {None, "sig"}:
                return None

            try:
                claims = self._decode(token, jwk, algorithm)
            except jwt.InvalidSignatureError:
                refreshed = await self._get_jwks(jwks_uri, force=True)
                refreshed_key = self._key_by_id(refreshed, key_id)
                if refreshed_key is None or refreshed_key == jwk:
                    return None
                claims = self._decode(token, refreshed_key, algorithm)
            subject = claims.get("sub")
            client_id = claims.get("client_id") or claims.get("azp") or subject
            if not isinstance(subject, str) or not subject:
                return None
            if not isinstance(client_id, str) or not client_id:
                return None
            scopes = self._parse_scopes(claims.get("scope"))
            if scopes is None or self._required_scope not in scopes:
                return None
            expires_at = claims.get("exp")
            if not isinstance(expires_at, int):
                return None
            return AccessToken(
                token=token,
                client_id=client_id,
                scopes=scopes,
                expires_at=expires_at,
                resource=self._audience,
                subject=subject,
                claims={"iss": self._issuer},
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError, jwt.PyJWTError):
            return None

    @staticmethod
    def _parse_scopes(value: object) -> list[str] | None:
        if isinstance(value, str):
            scopes = value.split()
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            scopes = value
        else:
            return None
        if not scopes or any(
            not scope or any(character.isspace() for character in scope) for scope in scopes
        ):
            return None
        return list(dict.fromkeys(scopes))

    async def _get_discovery(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._discovery is not None and self._discovery[0] > now:
            return self._discovery[1]
        async with self._discovery_lock:
            now = time.monotonic()
            if self._discovery is not None and self._discovery[0] > now:
                return self._discovery[1]
            discovery = await self._get_json(f"{self._issuer}/.well-known/openid-configuration")
            if discovery.get("issuer", "").rstrip("/") != self._issuer:
                raise ValueError("OIDC discovery issuer does not match configured issuer")
            jwks_uri = discovery.get("jwks_uri")
            parsed = urlparse(jwks_uri) if isinstance(jwks_uri, str) else None
            if (
                parsed is None
                or parsed.scheme != "https"
                or not parsed.netloc
                or parsed.username
                or parsed.password
            ):
                raise ValueError("OIDC discovery returned an invalid JWKS URI")
            self._discovery = (now + self._cache_ttl_seconds, discovery)
            return discovery

    async def _find_key(self, jwks_uri: str, key_id: str, *, force: bool) -> dict[str, Any] | None:
        jwks = await self._get_jwks(jwks_uri, force=force)
        return self._key_by_id(jwks, key_id)

    @staticmethod
    def _key_by_id(jwks: dict[str, Any], key_id: str) -> dict[str, Any] | None:
        for key in jwks["keys"]:
            if isinstance(key, dict) and key.get("kid") == key_id:
                return key
        return None

    async def _get_jwks(self, jwks_uri: str, *, force: bool) -> dict[str, Any]:
        now = time.monotonic()
        if not force and self._jwks is not None and self._jwks[0] > now:
            return self._jwks[1]
        async with self._jwks_lock:
            now = time.monotonic()
            if not force and self._jwks is not None and self._jwks[0] > now:
                return self._jwks[1]
            if (
                force
                and self._jwks is not None
                and now - self._last_forced_refresh < self._refresh_cooldown_seconds
            ):
                return self._jwks[1]
            jwks = await self._get_json(jwks_uri)
            if not isinstance(jwks.get("keys"), list):
                raise ValueError("OIDC JWKS response has no keys array")
            self._jwks = (now + self._cache_ttl_seconds, jwks)
            if force:
                self._last_forced_refresh = now
            return jwks

    def _decode(self, token: str, jwk: dict[str, Any], algorithm: str) -> dict[str, Any]:
        signing_key = jwt.PyJWK.from_dict(jwk, algorithm=algorithm).key
        return jwt.decode(
            token,
            signing_key,
            algorithms=self._algorithms,
            audience=self._audience,
            issuer=self._issuer,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )

    async def _get_json(self, url: str) -> dict[str, Any]:
        if self._client is None:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.get(url)
        else:
            response = await self._client.get(url, timeout=self._timeout_seconds)
        response.raise_for_status()
        if len(response.content) > _MAX_METADATA_BYTES:
            raise ValueError("OIDC metadata response is too large")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("OIDC metadata response must be an object")
        return payload
