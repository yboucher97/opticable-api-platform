"""Pure, bounded retry decisions. No provider call or sleep occurs here."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Literal

FailureCategory = Literal[
    "rate_limited", "network_timeout", "provider_unavailable",
    "authentication_expired", "permanent", "unknown",
]
RetryAction = Literal["retry", "dead_letter", "human_action_required"]


@dataclass(frozen=True)
class RetryDecision:
    action: RetryAction
    category: FailureCategory
    delay_seconds: float
    reason: str


def classify_failure(*, http_status: int | None = None,
                     network_timeout: bool = False) -> FailureCategory:
    if network_timeout and http_status is not None:
        raise ValueError("provide either HTTP status or network timeout")
    if network_timeout:
        return "network_timeout"
    if http_status is None:
        return "unknown"
    if not 100 <= http_status <= 599:
        raise ValueError("invalid HTTP status")
    if http_status == 429:
        return "rate_limited"
    if http_status == 408:
        return "network_timeout"
    if http_status in {401, 403}:
        return "authentication_expired"
    if 500 <= http_status <= 599:
        return "provider_unavailable"
    if 400 <= http_status <= 499:
        return "permanent"
    return "unknown"


def _retry_after_seconds(value: str, now: datetime) -> float:
    stripped = value.strip()
    if stripped.isascii() and stripped.isdecimal():
        return float(int(stripped))
    try:
        date = parsedate_to_datetime(stripped)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid Retry-After") from exc
    if date.tzinfo is None:
        raise ValueError("Retry-After date must include timezone")
    return max(0.0, (date.astimezone(timezone.utc) - now).total_seconds())


def decide_retry(*, attempt: int, safe_to_retry: bool,
                 http_status: int | None = None, network_timeout: bool = False,
                 retry_after: str | None = None, max_attempts: int = 5,
                 base_delay_seconds: float = 2.0, max_delay_seconds: float = 300.0,
                 jitter_fraction: float = 0.0, now: datetime | None = None) -> RetryDecision:
    """Classify one observed failure; callers must prove external idempotency.

    `safe_to_retry` must be false for an ambiguous external write. The function
    never authorizes a provider operation; it only returns a bounded decision.
    """
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 5:
        raise ValueError("max_attempts must be 1–5")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or not 1 <= attempt <= max_attempts:
        raise ValueError("attempt outside policy")
    if not 0 < base_delay_seconds <= 30 or not base_delay_seconds <= max_delay_seconds <= 300:
        raise ValueError("invalid bounded backoff")
    if not 0 <= jitter_fraction <= 1:
        raise ValueError("jitter fraction must be 0–1")
    checked_at = now or datetime.now(timezone.utc)
    if checked_at.tzinfo is None:
        raise ValueError("retry clock must be timezone-aware")
    checked_at = checked_at.astimezone(timezone.utc)

    category = classify_failure(http_status=http_status, network_timeout=network_timeout)
    if category == "authentication_expired":
        return RetryDecision("human_action_required", category, 0, "credential must be refreshed or reconciled")
    if category == "permanent":
        return RetryDecision("dead_letter", category, 0, "permanent provider response")
    if not safe_to_retry:
        return RetryDecision("human_action_required", category, 0, "external result may be ambiguous")
    if category == "unknown":
        return RetryDecision("dead_letter", category, 0, "unclassified failure is not retried")
    if attempt >= max_attempts:
        return RetryDecision("dead_letter", category, 0, "bounded retry attempts exhausted")

    delay = min(max_delay_seconds, base_delay_seconds * (2 ** (attempt - 1)))
    if retry_after is not None:
        try:
            provider_wait = _retry_after_seconds(retry_after, checked_at)
        except ValueError:
            return RetryDecision("human_action_required", category, 0, "invalid provider Retry-After")
        if provider_wait > max_delay_seconds:
            return RetryDecision("human_action_required", category, 0,
                                 "provider Retry-After exceeds bounded cooldown")
        delay = max(delay, provider_wait)
    delay = min(max_delay_seconds, delay * (1 + 0.2 * jitter_fraction))
    return RetryDecision("retry", category, delay, "bounded idempotent retry")
