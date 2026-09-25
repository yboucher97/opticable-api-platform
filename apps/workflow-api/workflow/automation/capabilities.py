from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import CapabilityRecord


def load_capabilities(path: Path) -> list[CapabilityRecord]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = raw.get("capabilities", []) if isinstance(raw, dict) else []
    return [CapabilityRecord.model_validate(item) for item in items]


def capability_summary(records: list[CapabilityRecord]) -> dict[str, Any]:
    if not records:
        return {"count": 0, "average_score": 0, "grade_counts": {}, "providers": {}}
    total = sum(item.score for item in records)
    grade_counts: dict[str, int] = {}
    providers: dict[str, dict[str, Any]] = {}
    for item in records:
        grade_counts[item.grade] = grade_counts.get(item.grade, 0) + 1
        provider = providers.setdefault(item.provider, {"count": 0, "score_total": 0, "minimum_score": 100})
        provider["count"] += 1
        provider["score_total"] += item.score
        provider["minimum_score"] = min(provider["minimum_score"], item.score)
    for provider in providers.values():
        provider["average_score"] = round(provider.pop("score_total") / provider["count"], 1)
    return {
        "count": len(records),
        "average_score": round(total / len(records), 1),
        "grade_counts": grade_counts,
        "providers": providers,
    }
