"""Pilot A/B driver — production caller for PILOT_VERDICT_SINK + compute_itt_delta.

Phase 0.2 → Phase 3 wiring: this is the FIRST production caller that actually
sets PILOT_VERDICT_SINK and consumes compute_itt_delta. Without it, runner.py's
sink-write paths are dead code and the §5.1 ITT backstop cannot be invoked on
real generated apps. R1 round-N binding NO-GO: "compute_itt_delta production
caller is zero."

Design (R1 binding requirements):

  * One CLI entrypoint. For EACH arm (ab_old, ab_new) it calls
    runner.run_app(app_dir, arm=ARM, run_id=...) N times so the JSONL sink
    accumulates BOTH pass-rows (synthesized by runner._emit_pass_verdict) and
    fail-rows (classified by runner._classify_and_emit). ITT needs both — a
    pass-only sink has no denominator-vs-numerator split, a fail-only sink has
    no passes for the rate.

  * PILOT_VERDICT_SINK is set in os.environ BEFORE run_app is invoked. runner
    reads it inside _classify_and_emit / _emit_pass_verdict at call time (see
    runner.py line 440, 467), so this driver simply mutates os.environ before
    each call. We do NOT propagate via docker_env — the sink write is in the
    runner's own process, not inside the container.

  * After all arm-runs complete, compute_itt_delta(sink, "ab_old", "ab_new")
    is called and BOTH the as-classified delta AND the ITT-worst-case delta
    are printed alongside the asymmetry-blocked flag. The §6.1 freeze
    criterion (4) wins-on-both-rates gate is then applied: a "win" requires
    POSITIVE delta on BOTH rates AND asymmetry not triggered.

  * DRY-RUN viability: this driver wraps the cheap part (run_app cycles
    against pre-generated app dirs). Generation is the expensive LLM-bound
    step; once you have two app trees on disk (e.g. reference_impl as the
    healthy ab_old surrogate and target_impl_broken as the unhealthy ab_new
    surrogate, or any two pre-generated trees) this driver validates the
    full PILOT_VERDICT_SINK → classify/synthesize → append_to_sink →
    compute_itt_delta chain with zero LLM cost.

CLI:

    python pilot_driver.py \\
        --spec simple_blog \\
        --app-dirs <ab_old_app_dir>,<ab_new_app_dir> \\
        --sink-path <path/to/sink.jsonl> \\
        [--runs-per-arm N] [--arm-names ab_old,ab_new] [--reset-sink]

Exit codes:
  0  — preflight ok, all arm-runs completed (pass or fail), ITT result printed
  2  — preflight failure: bad CLI args, missing app dirs, classifier import broken
  3  — runtime failure: runner module could not be imported / called at all
  4  — sink empty after all runs (no verdicts written; indicates the sink
       wiring is itself broken — the exact failure mode R1 was guarding against)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import List, Tuple


_THIS = Path(__file__).resolve()
_SIMPLE_BLOG_DIR = _THIS.parent
_NORTH_STAR_DIR = _SIMPLE_BLOG_DIR.parent
# Make both `runner` (sibling to this file) and `classifier` (in north_star/)
# importable without forcing the caller to fiddle with PYTHONPATH.
for p in (_SIMPLE_BLOG_DIR, _NORTH_STAR_DIR):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def _parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="pilot_driver",
        description=(
            "Drive run_app over A/B arms with PILOT_VERDICT_SINK set so the "
            "§5.1 ITT backstop can be invoked. Prints as-classified delta, "
            "ITT-worst-case delta, asymmetry-blocked flag, and the §6.1 "
            "wins-on-both-rates decision."
        ),
    )
    p.add_argument("--spec", required=True, help="Spec id (e.g. simple_blog).")
    p.add_argument(
        "--app-dirs",
        required=True,
        help=(
            "Comma-separated pair: <ab_old_app_dir>,<ab_new_app_dir>. "
            "Each must contain a docker-compose.yml that run_app can drive."
        ),
    )
    p.add_argument(
        "--sink-path",
        required=True,
        help="Absolute path to the JSONL sink file (created if absent).",
    )
    p.add_argument(
        "--runs-per-arm",
        type=int,
        default=1,
        help=(
            "How many times to invoke run_app per arm. ITT denominators need "
            ">=1; meaningful rate comparisons want >=3-5. Default 1 (smoke)."
        ),
    )
    p.add_argument(
        "--arm-names",
        default="ab_old,ab_new",
        help="Comma-separated arm labels matching --app-dirs order.",
    )
    p.add_argument(
        "--reset-sink",
        action="store_true",
        help=(
            "Delete --sink-path before starting so this driver invocation "
            "produces a clean, self-contained measurement. Without this the "
            "sink is appended to (multi-invocation pooling)."
        ),
    )
    return p.parse_args(argv)


def _preflight(args: argparse.Namespace) -> Tuple[List[Path], List[str]]:
    """Validate CLI inputs. Returns (app_paths, arm_names) on success;
    sys.exit(2) on any failure with a human-readable message."""
    dirs = [d.strip() for d in args.app_dirs.split(",") if d.strip()]
    arms = [a.strip() for a in args.arm_names.split(",") if a.strip()]
    if len(dirs) != 2 or len(arms) != 2:
        print(
            f"preflight FAIL: --app-dirs and --arm-names must each have exactly "
            f"2 comma-separated entries (got {len(dirs)} dirs, {len(arms)} arms).",
            file=sys.stderr,
        )
        sys.exit(2)
    app_paths: List[Path] = []
    for d in dirs:
        p = Path(d).resolve()
        if not (p / "docker-compose.yml").is_file():
            print(
                f"preflight FAIL: no docker-compose.yml under {p}", file=sys.stderr
            )
            sys.exit(2)
        app_paths.append(p)
    if args.runs_per_arm < 1:
        print("preflight FAIL: --runs-per-arm must be >= 1", file=sys.stderr)
        sys.exit(2)
    # Classifier must be importable — without it, runner's sink-write paths
    # short-circuit silently and we'd produce an empty sink with no error.
    try:
        import classifier  # noqa: F401
    except Exception as e:
        print(f"preflight FAIL: cannot import classifier ({e}).", file=sys.stderr)
        sys.exit(2)
    return app_paths, arms


def _drive_arm(
    runner_mod,
    app_path: Path,
    arm: str,
    spec: str,
    runs: int,
) -> List[Tuple[str, str]]:
    """Invoke run_app `runs` times for one arm, calling teardown after each.

    Returns a list of (run_id, status) where status is "pass" or "fail" — for
    operator-visible logging only; the authoritative record is the JSONL sink
    that runner.py wrote to inside _classify_and_emit / _emit_pass_verdict.
    """
    outcomes: List[Tuple[str, str]] = []
    for i in range(runs):
        run_id = uuid.uuid4().hex
        api_url, returned_path, reason = runner_mod.run_app(
            str(app_path), arm=arm, run_id=run_id
        )
        if api_url is not None:
            outcomes.append((run_id, "pass"))
            try:
                runner_mod.teardown(str(app_path))
            except Exception:
                pass  # teardown is best-effort by contract
        else:
            outcomes.append((run_id, f"fail: {reason}"))
            # teardown still — runner already attempted it for the health-fail
            # path, but a build/up failure may have left artifacts; idempotent.
            try:
                runner_mod.teardown(str(app_path))
            except Exception:
                pass
        # D4 propagation hook: after every run, the runner exposes its last
        # Verdict via get_last_verdict(). With the loud-on-swallow rewrite,
        # any fail-soft path now sets _last_verdict to a sentinel STRING
        # starting with 'INERT:' so we can detect "the measurement gate fired
        # but failed to produce a Verdict" — that is a HARD failure, NOT a
        # legitimate run. We refuse to ship a sink built on INERT runs.
        try:
            last_v = runner_mod.get_last_verdict()
        except Exception:
            last_v = None
        if isinstance(last_v, str) and last_v.startswith("INERT:"):
            print(
                f"  [arm={arm} run={i + 1}/{runs} run_id={run_id[:8]}] "
                f"INERT SENTINEL detected: {last_v} — measurement gate broken; "
                "aborting driver.",
                file=sys.stderr,
                flush=True,
            )
            raise SystemExit(4)
        print(
            f"  [arm={arm} run={i + 1}/{runs} run_id={run_id[:8]}] "
            f"{outcomes[-1][1]}",
            flush=True,
        )
    return outcomes


def _apply_wins_on_both_rates(itt_result: dict, arm_old: str, arm_new: str) -> dict:
    """§6.1 (4) gate: a "win" for ab_new requires POSITIVE delta on BOTH the
    as-classified and ITT-worst-case rates AND the asymmetry gate not
    triggered. Returns a decision dict suitable for json.dumps."""
    blocked = bool(itt_result.get("blocked"))
    as_delta = itt_result["as_classified"]["delta_pp"]
    itt_delta = itt_result["itt"]["delta_pp"]
    survives_as = as_delta > 0
    survives_itt = itt_delta > 0
    is_win = (not blocked) and survives_as and survives_itt
    reason = []
    if blocked:
        reason.append("asymmetry gate triggered")
    if not survives_as:
        reason.append(f"as-classified delta {as_delta:.2f}pp not positive")
    if not survives_itt:
        reason.append(f"ITT delta {itt_delta:.2f}pp not positive")
    return {
        "arm_old": arm_old,
        "arm_new": arm_new,
        "as_classified_delta_pp": as_delta,
        "itt_delta_pp": itt_delta,
        "asymmetry_blocked": blocked,
        "wins_on_both_rates": is_win,
        "verdict": "WIN" if is_win else "NO_WIN",
        "no_win_reasons": reason if not is_win else [],
    }


def main(argv: List[str]) -> int:
    args = _parse_args(argv)
    app_paths, arms = _preflight(args)

    # --- D2 HARD GATE: interpreter pin + preflight imports ------------------
    # MUST run before any worker spawns / any docker call / any runner import.
    # Failure means workers will go inert in run_app — abort the driver, NOT
    # the individual run (a failed run row would let ITT silently undercount).
    try:
        from pilot_preflight import (  # type: ignore
            PreflightError,
            _resolve_interpreter,
            run_preflight,
        )
    except Exception as e:
        print(
            f"preflight FAIL: cannot import pilot_preflight ({e}).",
            file=sys.stderr,
        )
        return 2
    # Resolve the pinned interpreter the SAME WAY workers will resolve it:
    # --python CLI flag (if argparse exposes it) > $PILOT_PYTHON > sys.executable.
    _pinned_python = (
        getattr(args, "python", None)
        or os.environ.get("PILOT_PYTHON")
        or sys.executable
    )
    try:
        _interp = _resolve_interpreter(_pinned_python)
        run_preflight(_interp)
    except (SystemExit, PreflightError) as _exc:
        print(
            f"pilot_driver: preflight FAILED — aborting before any run.\n{_exc}",
            file=sys.stderr,
        )
        return 2
    print(
        f"pilot_driver: preflight ok, pinned interpreter={_interp}",
        file=sys.stderr,
    )
    # Workers MUST be spawned with [_interp, ...] not ['python', ...] from
    # here on. Recommend: pass _interp explicitly into every subprocess /
    # multiprocessing spawn call so the pin is enforced, not hoped-for.
    # ------------------------------------------------------------------------

    sink_path = Path(args.sink_path).resolve()
    sink_path.parent.mkdir(parents=True, exist_ok=True)
    if args.reset_sink and sink_path.exists():
        sink_path.unlink()

    # MUST be set BEFORE run_app runs — runner reads os.environ at call time.
    os.environ["PILOT_VERDICT_SINK"] = str(sink_path)

    try:
        import runner as runner_mod
    except Exception as e:
        print(f"runtime FAIL: cannot import runner ({e}).", file=sys.stderr)
        return 3
    from classifier import compute_itt_delta, read_sink

    print(
        f"pilot_driver: spec={args.spec} sink={sink_path} "
        f"runs_per_arm={args.runs_per_arm}",
        flush=True,
    )
    for arm, app_path in zip(arms, app_paths):
        print(f"---- arm={arm} app_dir={app_path} ----", flush=True)
        _drive_arm(
            runner_mod, app_path, arm, args.spec, args.runs_per_arm
        )

    # Confirm the sink actually got rows — empty sink means the wiring is broken
    # (exactly the failure mode R1 was guarding against). Surface explicitly
    # rather than silently producing a zero-row ITT comparison.
    rows = list(read_sink(sink_path))
    if not rows:
        print(
            f"sink FAIL: {sink_path} has no rows after {len(arms)} arms × "
            f"{args.runs_per_arm} runs. PILOT_VERDICT_SINK wiring is broken; "
            "check that classifier is importable from runner.",
            file=sys.stderr,
        )
        return 4
    per_arm_observed = {arm: 0 for arm in arms}
    for r in rows:
        a = r.get("arm")
        if a in per_arm_observed:
            per_arm_observed[a] += 1
    print(f"sink rows by arm: {per_arm_observed}", flush=True)

    itt = compute_itt_delta(sink_path, arms[0], arms[1])
    decision = _apply_wins_on_both_rates(itt, arms[0], arms[1])

    print("---- ITT result ----", flush=True)
    print(json.dumps(itt, indent=2, default=str), flush=True)
    print("---- §6.1 wins-on-both-rates decision ----", flush=True)
    print(json.dumps(decision, indent=2), flush=True)

    # Exit 0: preflight ok + run complete + result printed. The win/no-win
    # bit lives in the JSON payload — the operator (or wrapping pipeline)
    # reads decision["wins_on_both_rates"] to act on it. We deliberately do
    # NOT exit non-zero on NO_WIN: NO_WIN is a valid outcome, not a driver
    # failure. Non-zero is reserved for "the driver itself could not produce
    # a comparable measurement."
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
