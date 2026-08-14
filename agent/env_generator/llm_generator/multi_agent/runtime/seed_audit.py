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


# #647: measured over the 43 delivered `seed_data.json` files (323 seeded tables, 10 distinct
# names): rows per table are p10 **5**, median 12, p90 32, max 124. The bar sits exactly on p10 —
# only **3%** of real tables fall below it, and just 2 fall below 3. Calibrated, not guessed; the
# number simply had no rationale recorded until this sweep.
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
                           # #694: say WHAT register_seed_data is. The old hint read as if the
                           # generated app needed a startup call, and that is exactly how it was
                           # read: an agent spent a multi-turn investigation on a "seed-gate
                           # blocker" and reported back "recommended routing a backend task to
                           # add register_seed_data() startup" — the wrong lane, the wrong
                           # artifact, and a task queued against app code that must never
                           # contain it. It is an AGENT-FACING HUB TOOL (tools/seed_tools.py:19,
                           # NAME = "register_seed_data"); the caller of this audit calls it
                           # itself after inserting rows. Same class as #682 and #690: the
                           # remediation text, not the detection, is what costs the rounds.
                           #
                           # Rare but expensive: `missing_seed` fires 14 times across 253 logs,
                           # because the loop above only examines tables still marked `defined`
                           # and 1632 of the corpus's 1648 table records are `implemented` by
                           # then. Low frequency, high per-firing cost — which is the argument
                           # for fixing the wording rather than the detector.
                           #
                           # #694b, two measurements that bound how bad the old wording was and
                           # add one thing the paragraph above does not cover. First the cost:
                           # `[backend] GREP pattern=register_seed_data scope=app/backend` runs
                           # 84 times across 18 runs, every one returning "0 matches", and 3
                           # runs escalate to `P0 delivery-gate: register_seed_data for all 12
                           # tables (0/12 registered)`. Then the outcome: 0 `seed_registered`
                           # events and registryhub_seed_registrations at _meta.version 1
                           # (create only) in 146 of 146 runs — the tool has never once been
                           # called successfully, so this hint has never yet led anywhere.
                           #
                           # And the part that is not just wording: the `seed` bundle is granted
                           # to orchestrator and verifier only — backend, frontend and debugger
                           # do not hold it (agents_config.yaml). "Call it yourself" is the
                           # right instruction for the audit's caller and an impossible one for
                           # whoever the blocker is dispatched to, which is `backend` in all 18
                           # of those runs. The sentence below therefore says what to do when
                           # you do not have the tool, rather than assuming you do. Changing the
                           # GRANT is a routing decision with blast radius past this audit and
                           # is deliberately not made here.
                           "hint": ("Seed this table, then call the `register_seed_data` HUB "
                                    "TOOL yourself to record the row count. Do NOT add a "
                                    "register_seed_data() call to the generated backend — it "
                                    "is not app code and nothing in the app can call it. "
                                    "It also requires the table to be registered first. If the "
                                    "tool is not in your toolset, do not go looking for it in "
                                    "the app — report that you lack it and hand the item back; "
                                    "it lives in the `seed` bundle, which not every role "
                                    "holds.")},
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


# ---------------------------------------------------------------------------
# Fix #54 — content-quality audit of the AUTHORED app/backend/seed_data.json.
# The #41 gate proves the lane authored SOMETHING; this proves it authored
# ENOUGH and authored it REALISTICALLY (info density + state realism = the top
# similarity lever, PIPELINE.md; run-33 shipped SUCCESS on a 2-row token seed).
# Deliberately CONSERVATIVE — it feeds a NON-WAIVABLE deliverability blocker, so
# every signal must be near-zero-false-positive (adversarial review w6x6art4t
# killed two draft signals for false-blocking realistic seeds: the sequential-
# name rule — 'msg_1' string FK ids / 'Room 101' / 'iPhone 15' ARE realistic —
# and the full marker list — 'test'/'sample'/'bar'/'tbd' are ordinary domain
# vocabulary). What remains:
#   * thin seed — fewer than ENVGEN_SEED_MIN_TOTAL_ROWS (default 10) structured
#     rows in TOTAL across all tables ("a dozen realistic emails … populated on
#     first load" needs double digits; any real authoring attempt clears this;
#     0 structured rows also lands here — a {table: ["str", ...]} shape passes
#     #41's non-empty-list check but seeds nothing);
#   * unambiguous placeholder markers — ≥2 DISTINCT words from the STRICT set
#     below on WORD BOUNDARIES in one table (unlike detect_placeholder_score's
#     substring match, "latest" must NOT hit "test" — and 'test'/'sample' are
#     not in this set at all: a QA-tracker's realistic seed says 'test' in
#     every row).
# ---------------------------------------------------------------------------

# #647: total seeded rows per run are median **119** (min 0, max 285) across 43 runs, so this
# floor separates "the lane authored nothing" from real data with a wide margin — only **3 of 43**
# runs fall below it, and those are the genuinely empty ones.
_MIN_AUTHORED_TOTAL_ROWS = 10

# Strict subset of _PLACEHOLDER_WORDS that is placeholder in ANY domain. The
# full set stays for the ADVISORY registration audit (waived once functionally
# validated); this hard-gate set must never collide with legitimate vocabulary.
_HARD_MARKER_WORDS = frozenset({
    "lorem", "ipsum", "placeholder", "dummy", "asdf", "qwerty", "xxxx",
    "foo", "baz", "qux", "example_user",
})


def _word_boundary_markers(rows: List[dict]) -> List[str]:
    """DISTINCT hard-marker words appearing on a word boundary in any string
    value of ``rows`` (case-insensitive)."""
    hits: Set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for v in row.values():
            if not isinstance(v, str):
                continue
            lowered = v.lower()
            for word in _HARD_MARKER_WORDS:
                if word in hits:
                    continue
                if re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", lowered):
                    hits.add(word)
    return sorted(hits)


def audit_authored_seed(data: Any) -> List[str]:
    """Content-quality issues with an authored seed mapping ({table: [rows]}).

    Returns human-readable issue strings ([] = acceptable). Pure + deterministic
    (recomputed each gate tick, so a rewritten seed self-clears); tolerant of
    arbitrary JSON shapes — non-dict input is not audited; non-dict ROWS are not
    counted as structured rows (so a strings-only "seed" can't satisfy the
    floor)."""
    import os
    if not isinstance(data, dict):
        return []
    try:
        min_total = int(os.environ.get("ENVGEN_SEED_MIN_TOTAL_ROWS",
                                       str(_MIN_AUTHORED_TOTAL_ROWS)))
    except Exception:
        min_total = _MIN_AUTHORED_TOTAL_ROWS
    issues: List[str] = []
    total = 0
    for table, rows in data.items():
        if not isinstance(rows, list):
            continue
        dict_rows = [r for r in rows if isinstance(r, dict)]
        total += len(dict_rows)
        if not dict_rows:
            continue
        markers = _word_boundary_markers(dict_rows)
        if len(markers) >= 2:
            issues.append(
                f"table '{table}' reads as placeholder content "
                f"(markers: {', '.join(markers[:5])}) — replace those exact "
                "values with believable domain content")
    if total < min_total:
        issues.append(
            f"only {total} structured row(s) (JSON objects) total across all "
            f"tables — populated list screens need >= {min_total}; add realistic "
            "rows (mixed states, believable names/subjects/timestamps) until the "
            "screens look like the references")
    return issues


def amplify_authored_seed(data: Any, min_total: int = None) -> Any:
    """FIX #84 (instagram run-5, live): deterministically AMPLIFY a realistic-but-thin
    authored seed to the density floor by cloning-and-perturbing the lane's OWN rows —
    the lane authored 9 believable rows, the gate demands >= 10, and 7 remediation
    dispatches went unanswered → STUCK-abort while the DB was already dense (the gate
    audits the FILE). The framework owns the density floor like #74 owns demo
    concentration.

    Clones get: a fresh pk (int max+n / string suffix), perturbed unique credentials
    (email/username/handle/slug), timestamps shifted minutes apart, and ``<x>_id`` FK
    values rotated within the seed's own ``<x>s`` id pool; the tuple of a clone's FK
    fields is deduped against every existing row so join-table UNIQUE constraints can't
    collide (an exhausted combo space just stops cloning that table). Marker-flagged
    (placeholder) seeds are NOT amplified — garbage×N is garbage; dense/clean seeds
    return None (untouched). Pure + deterministic; returns the amplified mapping or
    None when no change is needed/possible."""
    import copy
    import os
    issues = audit_authored_seed(data)
    if not issues or any("placeholder content" in i for i in issues):
        return None
    if not any("structured row" in i for i in issues):
        return None
    if min_total is None:
        try:
            min_total = int(os.environ.get("ENVGEN_SEED_MIN_TOTAL_ROWS",
                                           str(_MIN_AUTHORED_TOTAL_ROWS)))
        except Exception:
            min_total = _MIN_AUTHORED_TOTAL_ROWS

    out = copy.deepcopy(data)
    tables = {t: rows for t, rows in out.items()
              if isinstance(rows, list) and any(isinstance(r, dict) for r in rows)}
    if not tables:
        return None

    # id pools per table (for FK rotation) + existing FK-field combos per table
    pools: Dict[str, List[Any]] = {
        t: [r["id"] for r in rows if isinstance(r, dict) and r.get("id") is not None]
        for t, rows in tables.items()}
    int_id_next: Dict[str, int] = {
        t: (max([i for i in ids if isinstance(i, int)] or [0]) + 1)
        for t, ids in pools.items()}

    def _fk_fields(row: dict) -> List[str]:
        return sorted(k for k in row if k != "id" and str(k).endswith("_id"))

    def _combo(row: dict):
        return tuple((k, row.get(k)) for k in _fk_fields(row))

    seen_combos: Dict[str, set] = {}
    for t, rows in tables.items():
        seen_combos[t] = {_combo(r) for r in rows if isinstance(r, dict) and _fk_fields(r)}

    def _shift_ts(val: str, n: int) -> str:
        try:
            from datetime import datetime, timedelta
            s = str(val)
            suffix = "Z" if s.endswith("Z") else ""
            dt = datetime.fromisoformat(s.rstrip("Z"))
            return (dt + timedelta(minutes=7 * n + 3)).isoformat() + suffix
        except Exception:
            return val

    total = sum(len([r for r in rows if isinstance(r, dict)]) for rows in tables.values())
    n = 0
    stalled = False
    while total < min_total and not stalled:
        stalled = True
        for t, rows in tables.items():
            if total >= min_total:
                break
            src_rows = [r for r in rows if isinstance(r, dict)]
            if not src_rows:
                continue
            base = src_rows[n % len(src_rows)]
            clone = copy.deepcopy(base)
            n += 1
            # fresh pk
            if "id" in clone:
                if isinstance(clone["id"], int):
                    clone["id"] = int_id_next[t]
                    int_id_next[t] += 1
                else:
                    clone["id"] = f"{clone['id']}-a{n}"
            # unique credentials
            v = clone.get("email")
            if isinstance(v, str) and "@" in v:
                local, _, dom = v.partition("@")
                clone["email"] = f"{local}+a{n}@{dom}"
            for k in ("username", "handle", "slug"):
                if isinstance(clone.get(k), str):
                    clone[k] = f"{clone[k]}-a{n}"
            # timestamps drift apart
            for k, v in list(clone.items()):
                if str(k).endswith("_at") and isinstance(v, str):
                    clone[k] = _shift_ts(v, n)
            # rotate FK values within their pools; dedup the combo (UNIQUE safety)
            fks = _fk_fields(clone)
            placed = False
            for attempt in range(4 + max((len(pools.get(str(k)[:-3] + "s", []))
                                          for k in fks), default=0)):
                for k in fks:
                    ref = str(k)[:-3]
                    pool = pools.get(ref + "s") or pools.get(ref) or []
                    if pool:
                        cur = clone.get(k)
                        idx = (pool.index(cur) if cur in pool else 0)
                        clone[k] = pool[(idx + n + attempt) % len(pool)]
                if not fks or _combo(clone) not in seen_combos.get(t, set()):
                    placed = True
                    break
            if not placed:
                continue                                   # combo space exhausted → skip
            if fks:
                seen_combos.setdefault(t, set()).add(_combo(clone))
            rows.append(clone)
            if clone.get("id") is not None:
                pools.setdefault(t, []).append(clone["id"])
            total += 1
            stalled = False
    grew = total > sum(len([r for r in rows if isinstance(r, dict)])
                       for rows in data.values() if isinstance(rows, list))
    return out if grew else None


__all__ = ["SeedReport", "audit_seed_data", "detect_placeholder_score",
           "audit_authored_seed", "amplify_authored_seed"]
