"""Identity-aware Cloudflare Access verification for the Phase 6 operator surface.

The shared workflow API key is deliberately not accepted here. Only a verified
Cloudflare Access application JWT with a non-empty identity subject and verified
email can become a human outbound-approval principal.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Iterable

import jwt


_TEAM_DOMAIN = re.compile(r"https://[A-Za-z0-9][A-Za-z0-9.-]{0,126}\.cloudflareaccess\.com/?")
_SUBJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}")


@dataclass(frozen=True)
class AccessPrincipal:
    subject: str
    email: str
    actor: str


class AccessIdentityVerifier:
    """Validate Access application tokens and apply a local operator allowlist."""

    def __init__(
        self,
        *,
        team_domain: str,
        audience: str,
        allowed_subjects: Iterable[str] = (),
        allowed_emails: Iterable[str] = (),
        key_resolver: Callable[[str], object] | None = None,
    ) -> None:
        domain = str(team_domain or "").strip().rstrip("/")
        if not _TEAM_DOMAIN.fullmatch(domain):
            raise ValueError("invalid Cloudflare Access team domain")
        aud = str(audience or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._:-]{8,255}", aud):
            raise ValueError("invalid Cloudflare Access application audience")
        subjects = frozenset(str(value).strip() for value in allowed_subjects if str(value).strip())
        emails = frozenset(str(value).strip().lower() for value in allowed_emails if str(value).strip())
        if not subjects and not emails:
            raise ValueError("operator authorization allowlist is required")
        if any(not _SUBJECT.fullmatch(value) for value in subjects):
            raise ValueError("invalid allowed Access subject")
        if any(not _EMAIL.fullmatch(value) for value in emails):
            raise ValueError("invalid allowed Access email")
        self.team_domain = domain
        self.audience = aud
        self.allowed_subjects = subjects
        self.allowed_emails = emails
        self._jwk_client = None if key_resolver is not None else jwt.PyJWKClient(
            domain + "/cdn-cgi/access/certs",
            cache_keys=True,
            max_cached_keys=4,
        )
        self._key_resolver = key_resolver

    def _key(self, token: str):
        if self._key_resolver is not None:
            return self._key_resolver(token)
        return self._jwk_client.get_signing_key_from_jwt(token).key

    def verify(self, token: str | None) -> AccessPrincipal:
        value = str(token or "").strip()
        if not 64 <= len(value) <= 16384:
            raise ValueError("missing or invalid Cloudflare Access JWT")
        try:
            header = jwt.get_unverified_header(value)
        except Exception as exc:
            raise ValueError("invalid Cloudflare Access JWT header") from exc
        if header.get("alg") != "RS256" or header.get("typ") not in {None, "JWT"}:
            raise ValueError("unsupported Cloudflare Access JWT header")
        kid = header.get("kid")
        if not isinstance(kid, str) or not 1 <= len(kid) <= 256:
            raise ValueError("Cloudflare Access JWT key id is required")
        try:
            claims = jwt.decode(
                value,
                self._key(value),
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.team_domain,
                options={"require": ["aud", "exp", "iat", "iss", "nbf", "sub", "type"]},
                leeway=30,
            )
        except Exception as exc:
            raise ValueError("Cloudflare Access JWT verification failed") from exc
        if claims.get("type") != "app":
            raise ValueError("Cloudflare Access application token required")
        subject = claims.get("sub")
        email = claims.get("email")
        # Access service tokens have an empty sub and no verified human email.
        if not isinstance(subject, str) or not _SUBJECT.fullmatch(subject):
            raise ValueError("Cloudflare Access human subject required")
        if not isinstance(email, str) or not _EMAIL.fullmatch(email):
            raise ValueError("Cloudflare Access verified human email required")
        normalized_email = email.lower()
        authorized = subject in self.allowed_subjects or normalized_email in self.allowed_emails
        if not authorized:
            raise PermissionError("authenticated Access identity is not an outbound operator")
        return AccessPrincipal(subject=subject, email=normalized_email, actor="human:" + subject)
