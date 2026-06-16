"""Seed data audit (Cutover 21)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set


# Placeholder marker words (case-insensitive)
_PLACEHOLDER_WORDS = {
    "test", "foo", "bar", "baz", "qux", "asdf", "qwerty",
    "lorem", "ipsum", "placeholder", "dummy", "sample", "example_user",
    "todo", "tbd", "xxxx",
}

# Sequential name pattern: word followed by 1+ digits (e.g., user1, item_2, name3)
_SEQUENTIAL_RE = re.compile(r"^[a-zA-Z_]+[\s_-]?\d+$")


def detect_placeholder_score(rows: List[dict]) -> float:
    if not rows:
        return 0.0
    score = 0.0

    # 1. Generic placeholder words in any string value
    # Each distinct placeholder word per value counts once (so "lorem ipsum"
    # in one value scores both 'lorem' and 'ipsum').
    placeholder_hit_count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        for v in row.values():
            if not isinstance(v, str):
                continue
            lowered = v.lower()
            for word in _PLACEHOLDER_WORDS:
                if word in lowered:
                    placeholder_hit_count += 1
    score += min(placeholder_hit_count, 5) * 0.15

    # 2. Sequential-name pattern
    sequential_hits = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        for v in row.values():
            if not isinstance(v, str):
                continue
            if _SEQUENTIAL_RE.match(v.strip()):
                sequential_hits += 1
                break
    score += min(sequential_hits, 3) * 0.30

    # 3. All-same-boolean across rows (only if >=3 rows)
    if len(rows) >= 3:
        bool_columns: Dict[str, Set[bool]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            for k, v in row.items():
                if isinstance(v, bool):
                    bool_columns.setdefault(k, set()).add(v)
        for vals in bool_columns.values():
            if len(vals) == 1:
                score += 0.20
                break  # only count once

    return min(score, 1.0)


@dataclass
class SeedReport:
    flagged_tables: List[dict] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.flagged_tables

    @property
    def all_flagged_paths(self) -> Set[str]:
        return {f"seed:{f['table']}" for f in self.flagged_tables}

    def to_dict(self) -> dict:
        return {
            "flagged_tables": list(self.flagged_tables),
            "is_clean": self.is_clean,
        }


_DEFAULT_MIN_ROWS = 5
_PLACEHOLDER_THRESHOLD = 0.5


def audit_seed_data(hub_registry) -> SeedReport:
    schema_hub = getattr(hub_registry, "schema_hub", None)
    if schema_hub is None or not hasattr(schema_hub, "list_tables"):
        return SeedReport()
    tables = schema_hub.list_tables() or {}
    seed_regs = schema_hub.list_seed_registrations() or {}

    flagged: List[dict] = []
    for name, table in tables.items():
        if (table.get("status") or "defined") != "defined":
            continue
        meta = table.get("metadata") or {}
        min_rows = meta.get("min_seed_rows", _DEFAULT_MIN_ROWS)
        if min_rows == 0:
            continue  # explicit opt-out

        reg = seed_regs.get(name)
        if reg is None:
            flagged.append({
                "table": name,
                "reason": "missing_seed",
                "detail": {"min_seed_rows": min_rows,
                           "hint": "call register_seed_data after seeding"},
            })
            continue

        row_count = reg.get("row_count", 0)
        if row_count < min_rows:
            flagged.append({
                "table": name,
                "reason": "low_row_count",
                "detail": {"row_count": row_count,
                           "min_seed_rows": min_rows},
            })
            continue

        score = detect_placeholder_score(reg.get("sample_excerpt") or [])
        if score >= _PLACEHOLDER_THRESHOLD:
            flagged.append({
                "table": name,
                "reason": "placeholder_content",
                "detail": {"placeholder_score": round(score, 2),
                           "threshold": _PLACEHOLDER_THRESHOLD,
                           "sample_size": len(reg.get("sample_excerpt") or [])},
            })

    return SeedReport(flagged_tables=flagged)


__all__ = ["SeedReport", "audit_seed_data", "detect_placeholder_score"]
