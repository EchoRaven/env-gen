#!/usr/bin/env python3
"""Read one generation run's outcome from its artifacts. `python3 tools/readout_run.py netflix-web-r154`

★ Why this exists as a FILE rather than a shell one-liner: this session answered the same questions
about r153 a dozen times with ad-hoc probes and got the probe wrong fourteen times — a `_meta` key
counted as a record, a relative path compared against a resolved one, an `app_root` pointed one
directory too high, a regex that missed JSON's escaped quotes. Every one of those produced a
confident number. A readout that is written once, calibrated against a run whose answers are
already known, and then reused cannot drift the way a retyped probe does.

Calibrated against r153 (see `--selftest`): 19 ui_pages, 12 judged screens, 4 of 7 blocking at
0.65, releases 1.0.0 + 1.1.0, and #919 firing on my-list + continue-watching.
"""
from __future__ import annotations

# ★ RUN THIS WITH THE REPO VENV:  agent/../.venv/bin/python tools/readout_run.py <run>
# The system interpreter lacks the framework's dependencies, and the gate section then reports
# `None` for every finding rather than failing loudly — a silent zero from the wrong interpreter.
# `--selftest` catches it (it did, on this file's first run), which is why the selftest exists.

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1] / "agent"

SIGNALS = ("STAGE ", "LANE PAGE WITH OWN COMPONENTS", "PROJECTION CLOBBER",
           "AUTH PAGE OVERWRITE", "COMPONENT DRIFT", "API UNREACHABLE",
           "unscoped owner read", "TOTAL BLACKOUT", "ROUND BUDGET SPENT",
           "MILESTONE ROADMAP DID NOT LAND", "SERVED-BUILD STAMP UNREADABLE")


def _j(p):
    try:
        return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))
    except Exception:
        return None


def readout(run: str) -> dict:
    d = ROOT / "generated" / run
    log = ROOT.parent / f"gm_{run}.log"
    out: dict = {"run": run, "exists": d.is_dir()}
    if not d.is_dir():
        return out

    # releases — keyed by tag; `_meta` is the store's schema row, not a release
    rel = _j(d / "shared/hubs/codehub_releases.json") or {}
    out["releases"] = sorted(k for k in rel if k != "_meta") if isinstance(rel, dict) else []

    # ui_pages — same exclusion
    up = _j(d / "shared/hubs/registryhub_ui_pages.json") or {}
    recs = [v for k, v in up.items() if isinstance(v, dict) and k != "_meta"] \
        if isinstance(up, dict) else []
    out["ui_pages"] = len(recs)
    out["ui_pages_blank_route"] = sum(1 for r in recs if not str(r.get("route") or "").strip())

    # visual verdict
    v = _j(d / "design/visual_gate/verdict.json") or {}
    screens = v.get("screens") or []
    blocking = [s for s in screens if not s.get("advisory")]
    out["screens"] = len(screens)
    out["blocking"] = len(blocking)
    out["blocking_at_bar"] = sum(1 for s in blocking if (s.get("similarity") or 0) >= 0.65)
    out["blocking_mean"] = round(
        sum((s.get("similarity") or 0) for s in blocking) / len(blocking), 4) if blocking else None
    out["per_screen"] = sorted(((str(s.get("name")), s.get("similarity"),
                                 bool(s.get("advisory"))) for s in screens),
                               key=lambda t: -(t[1] or 0))
    cov = v.get("coverage")
    out["coverage_has_scope_921"] = isinstance(cov, dict) and "scope" in cov

    # lane wake-up, minutes from the first agent log
    times = {}
    alog = d / ".agent_logs"
    if alog.is_dir():
        for sub in alog.iterdir():
            fs = [f for f in sub.rglob("*") if f.is_file()]
            times[sub.name.split()[0]] = min(f.stat().st_mtime for f in fs) if fs else None
    base = min([t for t in times.values() if t], default=None)
    out["lane_first_write_min"] = {
        k: (round((t - base) / 60, 1) if t else None) for k, t in sorted(times.items())} \
        if base else {}

    # log signals
    out["signals"] = {}
    if log.is_file():
        try:
            text = log.read_text(encoding="utf-8", errors="ignore")
            out["signals"] = {s: text.count(s) for s in SIGNALS}
        except Exception:
            pass

    # live gate findings on the delivered tree
    sys.path.insert(0, str(ROOT))

    # ── artifacts introduced 2026-08-17/18 (#930–#951). ★ Absent is reported as None, never as
    # zero: r154 predates all of these, and "not recorded" must not read as "nothing happened"
    # (#907). The selftest pins exactly that on r154.
    def _lines(rel):
        f = d / rel
        if not f.is_file():
            return None
        out_ = []
        for ln in f.read_text(encoding="utf-8", errors="replace").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                out_.append(json.loads(ln))
            except Exception:
                pass
        return out_

    pf = _j(d / "logs/preflight.json")                                   # #944
    out["preflight"] = None if pf is None else {
        "docker": (pf.get("docker") or {}).get("available"),
        "compose_provider": (pf.get("compose") or {}).get("provider"),
        "compose_service_ps": (pf.get("compose") or {}).get("service_ps"),
        "remedy": bool((pf.get("docker") or {}).get("remedy")),
    }

    gl = _lines("logs/delivery_gate.jsonl")                              # #948
    out["gate_evals"] = None if gl is None else len(gl)
    out["gate_first_ok_at"] = None if not gl else next(
        (i + 1 for i, r in enumerate(gl) if r.get("ok")), None)
    out["gate_failed_checks_seen"] = None if not gl else sorted(
        {c for r in gl for c in (r.get("failed_checks") or [])})

    rl = _lines("design/visual_gate/rounds.jsonl")
    out["rounds"] = None if rl is None else len(rl)
    if rl:
        # #937 — distinct renderings per screen: the number that took three detours in r154
        fps: dict = {}
        for r in rl:
            for k, v in (r.get("capture_md5_937") or {}).items():
                fps.setdefault(k, set()).add(v)
        out["distinct_renderings"] = {k: len(v) for k, v in sorted(fps.items())} or None
        # ★ None, not 0, when NO round carries the key — r154 has 12 rounds and no
        # `zero_reasons_933` at all, and this line reported 0, which reads as "12 rounds, none
        # had a zero reason". My own selftest exists to catch exactly that and I had left this
        # field off the list it checks. Absent and none-of-them are different facts (#907).
        out["rounds_with_zero_reasons"] = (
            sum(1 for r in rl if r.get("zero_reasons_933"))
            if any("zero_reasons_933" in r for r in rl) else None)                          # #933
        out["milestones_in_ledger"] = sorted({r["milestone"] for r in rl
                                              if r.get("milestone")}) or None               # #941
        out["capture_errors_seen"] = sorted({                                               # #935
            (z or {}).get("capture_error") for r in rl
            for z in (r.get("zero_reasons_933") or {}).values()
            if (z or {}).get("capture_error")}) or None

    ow = _j(d / "design/scaffold_overwrites_939.json")                   # #939 / #951
    out["overwrite_loops"] = None if ow is None else {
        k: v for k, v in sorted(ow.items()) if isinstance(v, int) and v >= 2} or {}
    ex = _j(d / "design/lane_page_exposure_946.json")                    # #946 — decision 1a
    out["lane_page_exposure"] = None if ex is None else {
        k: {"lane": v.get("lane_lines"), "proj": v.get("projection_lines")}
        for k, v in sorted(ex.items())}
    caps = d / "design/visual_gate/captures"                             # #930
    out["archived_captures"] = len(list(caps.glob("*.png"))) if caps.is_dir() else None
    out["served_build_stamped"] = (d / "design/visual_gate/served_build.json").is_file()  # #936


    try:
        from env_generator.llm_generator.multi_agent.runtime import deliverability as dv
        from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa
        app = d / "app"
        out["gate_919_owner_read"] = len(dv._unscoped_owner_read_blockers(app)) if app.is_dir() else None
        out["gate_173_stub"] = len(dv._stub_handler_blockers(app)) if app.is_dir() else None
        src = app / "frontend" / "src"
        out["gate_175_invented"] = len(fa.invented_field_fallback_blockers(src)) if src.is_dir() else None
    except Exception as exc:
        out["gate_error"] = f"{type(exc).__name__}: {exc}"
    return out


def selftest() -> int:
    """★ Calibration, not decoration: the tool must reproduce r153's known answers."""
    r = readout("netflix-web-r153")
    expect = {"ui_pages": 19, "screens": 12, "blocking": 7, "blocking_at_bar": 4,
              "releases": ["1.0.0", "1.1.0"], "gate_919_owner_read": 2}
    bad = [f"{k}: got {r.get(k)!r}, expected {v!r}" for k, v in expect.items() if r.get(k) != v]

    # ★ Second calibration, added with the #930–#951 fields: r154 predates every one of them, so
    # each MUST read None — "not recorded" — and not 0. A reader who sees `overwrite_loops: {}`
    # on r154 would conclude the loop never happened; it happened 19 times and nothing counted it.
    # This is #907's rule turned into a test of the reporting tool itself.
    r154 = readout("netflix-web-r154")
    for k in ("preflight", "gate_evals", "overwrite_loops", "lane_page_exposure",
              "archived_captures", "rounds_with_zero_reasons", "distinct_renderings",
              "milestones_in_ledger", "capture_errors_seen"):
        if r154.get(k) is not None:
            bad.append(f"r154.{k}: got {r154.get(k)!r}, expected None (predates the field)")
    # …and the fields r154 DOES have must still read, or the tool is silently blind
    if not r154.get("rounds"):
        bad.append(f"r154.rounds: got {r154.get('rounds')!r}, expected 12")
    if r154.get("served_build_stamped") is not False:
        bad.append("r154.served_build_stamped should be False — #738 never wrote one")

    for line in bad:
        print("  MISMATCH", line)
    print("selftest:", "OK" if not bad else "FAILED")
    return 1 if bad else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    name = sys.argv[1] if len(sys.argv) > 1 else "netflix-web-r154"
    print(json.dumps(readout(name), indent=2, ensure_ascii=False))
