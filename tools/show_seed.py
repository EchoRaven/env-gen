#!/usr/bin/env python3
"""Inspect a generated env's seed DATA conveniently.

The backend agent authors ``app/backend/seed_data.json`` (the framework's seed_data.py
loader consumes it). This prints a per-table summary + sample rows AND flags common
quality problems, so you can judge the agent's seed at a glance instead of opening the
raw file:

    python tools/show_seed.py outlook-seed1        # env name under generated/
    python tools/show_seed.py /path/to/app/backend # or a direct path

Flags: stringified numbers/booleans ("3"/"True"), generic framework-placeholder values
(the agent didn't add domain realism), and owner-scoped rows missing their owner.
Dev helper — not shipped.
"""
import json
import sys
from pathlib import Path

_PLACEHOLDER = {"Getting Started", "Project Overview", "Weekly Summary",
                "Quarterly Plan", "Team Update", "Field Report"}
_REPO = Path(__file__).resolve().parents[1]


def _find(arg: str) -> Path:
    p = Path(arg)
    for cand in (p / "seed_data.json",
                 p / "app/backend/seed_data.json",
                 _REPO / "generated" / arg / "app/backend/seed_data.json"):
        if cand.is_file():
            return cand
    sys.exit(f"no seed_data.json found for {arg!r} "
             f"(looked under generated/{arg}/app/backend/ and {arg})")


def _looks_stringy(v) -> bool:
    return isinstance(v, str) and (v in ("True", "False", "true", "false")
                                   or (v.lstrip("-").isdigit()))


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    path = _find(sys.argv[1])
    data = json.loads(path.read_text(encoding="utf-8"))
    print(f"\nseed: {path}  ({path.stat().st_size} bytes)\n" + "=" * 64)
    issues = []
    for table, rows in data.items():
        if not isinstance(rows, list):
            continue
        print(f"\n▸ {table}  ({len(rows)} rows)")
        for r in rows[:2]:
            if isinstance(r, dict):
                shown = {k: (str(v)[:46]) for k, v in list(r.items())[:7]}
                print(f"    {shown}")
        # ---- quality flags ----
        sample = rows[0] if rows and isinstance(rows[0], dict) else {}
        stringy = [k for k, v in sample.items() if _looks_stringy(v)]
        if stringy:
            issues.append(f"{table}: stringified values {stringy} (use JSON 3 / true, not \"3\" / \"True\")")
        placeheld = sorted({str(v) for r in rows if isinstance(r, dict)
                            for v in r.values() if str(v) in _PLACEHOLDER})
        if placeheld:
            issues.append(f"{table}: framework PLACEHOLDER values {placeheld} — agent added no realism")
        owner_cols = [c for c in ("user_id", "author_id", "owner_id") if c in sample]
        if owner_cols and table != "users":
            oc = owner_cols[0]
            missing = sum(1 for r in rows if isinstance(r, dict) and not r.get(oc))
            if missing:
                issues.append(f"{table}: {missing}/{len(rows)} rows missing owner {oc!r}")
    print("\n" + "=" * 64)
    if issues:
        print("⚠ QUALITY FLAGS:")
        for it in issues:
            print(f"  - {it}")
    else:
        print("✓ no obvious quality flags (types clean, no placeholders, owners set)")
    print()


if __name__ == "__main__":
    main()
