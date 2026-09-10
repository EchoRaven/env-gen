"""#1202bw — RESTORE POINTS for a long run.

A run's coordination state is already durable: ``shared/hubs/`` is file-backed JsonStore
that re-reads on every access, ``app/`` and ``worktrees/`` are git, ``run_budget.json`` and
``.checkpoint`` are on disk. So "resume" has never been blocked by lost state.

What was missing is a way to go BACK. JsonStore rewrites each file in place, so the only
state a run has is its LATEST state — and for a run that has wedged (r34: 20 LoginPage
overwrites, no gate progress for 42 minutes while $92 burned) the latest state IS the
wedged state. Resuming into it just resumes the wedge. This module keeps periodic copies so
an operator can rewind to a tick that was still making progress and continue from there
instead of paying for a whole fresh run.

CONSISTENCY, stated honestly: ``JsonStore._save_raw`` writes tmp + ``os.replace``, so every
individual file copied here is atomically-written and can never be torn. Files are NOT
captured under a global lock, so two files may come from moments milliseconds apart. That
is the same consistency a resume has always had (the hubs are eventually-consistent
ledgers, and lanes reconcile against them), so this adds no weakness — but it is a copy,
not a transaction, and nothing here should be described as one.

Cadence (all optional, read at call time so a live run can be retuned by restarting):
  ENVGEN_SNAPSHOT_EVERY_MIN     interval between automatic snapshots (default 20; 0 = off)
  ENVGEN_SNAPSHOT_ON_MILESTONE  snapshot at each milestone boundary (default 1)
  ENVGEN_SNAPSHOT_KEEP          how many to retain PER KIND (default 5; 0 = unlimited)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional

# Copied wholesale. `shared/hubs` is the coordination ledger — tasks, events, code state,
# registry — and is the only directory a resume genuinely cannot re-derive.
# #1202cs: `design/visual_gate` belongs here for the same reason — it is the ONLY
# record of what the run has already WON. #500's best-ever-per-screen merge reads
# `verdict.json` back off disk, and gate_state.json carries deferred_since /
# total_judgments / plateau_rounds / released. A snapshot without them restores a run
# that has forgotten every screen score it ever earned, with the escape timer and
# plateau detection back at zero — the "two rounds spent re-winning points already
# won" failure, reintroduced by the very mechanism meant to prevent lost work.
_STATE_DIRS = ("shared/hubs",)

# #1202cs: `design/visual_gate` is captured, but only its LEDGER. Measured on r41: the
# whole directory is 107MB against 8.9MB for the rest of the snapshot, and 97MB of that
# is PNGs — reference frames and per-round captures that a resumed run RE-TAKES anyway.
# The state that cannot be re-derived is 472KB of JSON. Disk has been this project's
# binding constraint, and `_KEEP` multiplies every snapshot, so copying the images would
# trade one lost-work bug for a full disk.
# #1202ey: the JSON-only rule now covers `design` ENTIRE, not just its visual_gate subdir.
# Naming one subdirectory made the capture list a hand-maintained inventory, and an
# inventory is missing whatever was added after it was written: `design/milestone_gates.json`
# -- the orchestrator's gate counters (`_fwval_stuck_count`, `_tu_squad_attempts`,
# `_framework_validation_attempts`, `_pages_gate_deferred_since`) -- was never captured. Those
# counters are BOUNDS. Restoring a snapshot rewound the hubs to time T while the bounds stayed
# at whatever the abandoned attempt had spent, so the restored run inherited exhausted budgets
# its own work state had never used. A restore point that is a blend of two moments is exactly
# what take_snapshot's own suffix logic exists to prevent, and this was that blend.
#
# `design/lane_page_exposure_946.json` and `design/reference_spec.json` come along, which
# matters for the second one: a resume RECOMPILES the reference spec (#1202eo), so a snapshot
# is now the way to undo a bad recompile.
#
# Still JSON-only, and the reason is unchanged and re-measured: across 47 runs design/ holds
# 0.34MB of JSON at the median and 1.28MB at the most, against 170-265MB of images beside it.
# The rule keeps #1202cs's saving while removing the inventory.
_STATE_DIRS_JSON_ONLY_1202CS = ("design", "test_user_reports")
_JSON_SUFFIXES_1202CS = (".json", ".jsonl")

# Copied individually. design_system.json is here because it is the single most expensive
# artifact in a run (#1202bv lets a resume inherit it); the rest are small and pin the run's
# identity and spend.
_STATE_FILES = (
    ".checkpoint",
    "run_budget.json",
    "project.json",
    # #1202ey: `.user_gates.json` is a top-level dotfile, so no directory rule reaches it.
    ".user_gates.json",
    # Both design files are now also covered by the `design` rule above. Kept named so a
    # future narrowing of that rule cannot silently drop the run's most expensive artifact.
    "design/design_system.json",
    "design/.design_prep_input.json",
)

# JsonStore leaves `.lock` sentinels and, when a write dies partway, `.<pid>.tmp` orphans
# (#1202ap measured 5 across the corpus, worst 2.4MB). Neither is state; copying them would
# restore a stale lock and re-plant the orphans a later cleanup is meant to reclaim.
_SKIP_SUFFIXES = (".lock", ".tmp")

_MANIFEST = "manifest.json"
_KIND_MILESTONE = "milestone"
_KIND_INTERVAL = "interval"
_KIND_MANUAL = "manual"

_last_snapshot_ts: Dict[str, float] = {}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except Exception:
        return default


def snapshots_root(output_dir) -> Path:
    return Path(output_dir) / "snapshots"


def _skip(p: Path) -> bool:
    return any(str(p.name).endswith(s) for s in _SKIP_SUFFIXES)


def take_snapshot(output_dir, kind: str = _KIND_MANUAL,
                  label: str = "") -> Optional[Path]:
    """Copy the run's restorable state into ``snapshots/<ts>-<kind>-<label>/``.

    Best-effort by design: a snapshot is an OPTIONAL safety net, and a run must never die
    because one could not be written. Returns the directory, or None if nothing was
    captured (which is itself logged into the manifest of the next successful one).
    """
    out = Path(output_dir)
    root = snapshots_root(out)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = f"{stamp}-{kind}" + (f"-{label}" if label else "")
    # The stamp resolves to the SECOND, so two snapshots of the same kind and label inside
    # one second would land on the same path and `mkdir(exist_ok=True)` would silently MERGE
    # them into one half-and-half directory. Suffix instead: a restore point that is a blend
    # of two moments is worse than no restore point at all.
    name, _n = base, 1
    while (root / name).exists():
        name = f"{base}.{_n}"
        _n += 1
    dest = root / name
    copied: List[str] = []
    failed: List[str] = []
    total = 0
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None

    for rel in _STATE_DIRS + _STATE_DIRS_JSON_ONLY_1202CS:
        src = out / rel
        if not src.is_dir():
            continue
        json_only = rel in _STATE_DIRS_JSON_ONLY_1202CS
        for f in sorted(src.rglob("*")):
            if not f.is_file() or _skip(f):
                continue
            if json_only and f.suffix.lower() not in _JSON_SUFFIXES_1202CS:
                continue
            try:
                r = f.relative_to(out)
                tgt = dest / r
                tgt.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, tgt)
                copied.append(str(r))
                total += tgt.stat().st_size
            except Exception:
                failed.append(str(f.relative_to(out)))

    for rel in _STATE_FILES:
        src = out / rel
        if not src.is_file() or _skip(src):
            continue
        try:
            tgt = dest / rel
            tgt.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, tgt)
            copied.append(rel)
            total += tgt.stat().st_size
        except Exception:
            failed.append(rel)

    if not copied:
        try:
            shutil.rmtree(dest, ignore_errors=True)
        except Exception:
            pass
        return None

    try:
        (dest / _MANIFEST).write_text(json.dumps({
            "created": stamp,
            "epoch": time.time(),
            "kind": kind,
            "label": label,
            "files": len(copied),
            "bytes": total,
            "failed": failed,
        }, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        pass

    _last_snapshot_ts[str(out)] = time.time()
    _prune(out, kind)
    return dest


def _prune(output_dir, kind: str) -> None:
    """Retain the newest ``ENVGEN_SNAPSHOT_KEEP`` PER KIND.

    Per kind, not overall, on purpose: the most valuable restore point is usually the last
    milestone boundary, and a long tail of interval snapshots would evict exactly that one
    under a single global budget.
    """
    keep = _env_int("ENVGEN_SNAPSHOT_KEEP", 5)
    if keep <= 0:
        return
    try:
        same = sorted((d for d in snapshots_root(output_dir).iterdir()
                       if d.is_dir() and _kind_of(d) == kind),
                      key=_order_key)
        for d in same[:-keep]:
            shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass


def _order_key(d: Path):
    """Chronological order.

    Sorting by directory NAME looks equivalent — names are timestamp-prefixed — but the
    stamp resolves only to the second, so two snapshots inside one second fall back to
    alphabetical order on the KIND, which is not chronological at all. Both the operator's
    listing ("newest last") and `_prune` ("drop all but the newest N") read this order, so
    a tie there can delete the NEWER snapshot. The manifest's float epoch breaks the tie.
    """
    try:
        m = json.loads((d / _MANIFEST).read_text(encoding="utf-8"))
        e = m.get("epoch")
        if isinstance(e, (int, float)):
            return (float(e), d.name)
    except Exception:
        pass
    return (float("inf"), d.name)


def _kind_of(d: Path) -> str:
    try:
        m = json.loads((d / _MANIFEST).read_text(encoding="utf-8"))
        k = m.get("kind")
        if isinstance(k, str) and k:
            return k
    except Exception:
        pass
    parts = d.name.split("-")
    return parts[2] if len(parts) > 2 else ""


def maybe_snapshot(output_dir, kind: str = _KIND_INTERVAL,
                   label: str = "") -> Optional[Path]:
    """Cadence gate for the automatic call sites. Returns the snapshot, or None when it is
    not due yet / disabled."""
    if kind == _KIND_MILESTONE:
        if _env_int("ENVGEN_SNAPSHOT_ON_MILESTONE", 1) <= 0:
            return None
        _warn_if_nothing_scored_1202hy(output_dir, _LOG_1202HY)
        return take_snapshot(output_dir, kind, label)

    every = _env_int("ENVGEN_SNAPSHOT_EVERY_MIN", 20)
    if every <= 0:
        return None
    key = str(Path(output_dir))
    last = _last_snapshot_ts.get(key)
    if last is None:
        # First call establishes the clock rather than snapshotting a run that has barely
        # started — an empty ledger is not a restore point worth keeping.
        _last_snapshot_ts[key] = time.time()
        return None
    if (time.time() - last) < every * 60:
        return None
    _warn_if_nothing_scored_1202hy(output_dir, _LOG_1202HY)
    return take_snapshot(output_dir, kind, label)


# #1202hy: SPENDING WITH NOTHING SCORED, SAID WHILE IT IS STILL HAPPENING.
#
# #1202di put "⚠ NOTHING SCORED" in the snapshot listing, which is read AFTER the run is
# over and someone is choosing what to rewind to. Nothing said it during the run, so the
# spend kept going: across seven runs on this corpus, $814 accumulated in states where
# the visual gate had never judged a single screen.
#
# Validated against the run that DELIVERED before being believed, because "no screens yet"
# could simply be what the first minutes of any run look like:
#
#     r97 (delivered)   first snapshot ALREADY judged=1 at $43; no zero-judgment snapshot
#     r106              judged=0 through $165 before the first score
#     r102              judged=0 at EVERY snapshot -- it never scored anything at all
#
# It discriminates, so the threshold is anchored on r97: a healthy run has judged
# something by roughly $50. Warning only -- a run legitimately builds before it can be
# photographed, and the operator is the one who decides whether to keep paying.
_LOG_1202HY = logging.getLogger("multi_agent.runtime.run_snapshot")
_NOTHING_SCORED_WARNED_1202HY: Dict[str, bool] = {}


def _warn_if_nothing_scored_1202hy(output_dir, logger=None) -> Optional[str]:
    """Say once that this run is paying without having judged a screen. Returns the text.

    Reads the LIVE ledger and gate rather than the snapshot just taken: milestone
    snapshots record usd=0 (the ledger is rewritten around that boundary), so a threshold
    read out of one would never fire on exactly the runs it is meant to catch.
    """
    try:
        key = str(Path(output_dir))
        if _NOTHING_SCORED_WARNED_1202HY.get(key):
            return None
        # #1202kc: an EMPTY value is not a zero. `os.environ.get(name, "50") or 0` returns 0
        # for `ENVGEN_NOTHING_SCORED_WARN_USD=` — which a shell writes whenever the variable
        # it expands is itself unset — and `floor <= 0` then disables this warning for the
        # whole run, silently. Disabling it is a legitimate choice; making it by typo is not,
        # and nothing distinguished the two. Blank now means "use the default"; only an
        # explicit number turns it off, and turning it off says so once.
        _raw_1202kc = os.environ.get("ENVGEN_NOTHING_SCORED_WARN_USD")
        if _raw_1202kc is None or not str(_raw_1202kc).strip():
            floor = 50.0
        else:
            try:
                floor = float(str(_raw_1202kc).strip())
            except (TypeError, ValueError):
                _LOG_1202HY.warning(
                    "#1202kc ENVGEN_NOTHING_SCORED_WARN_USD=%r is not a number — using the "
                    "$50 default rather than silently dropping the guard.", _raw_1202kc)
                floor = 50.0
        if floor <= 0:
            _LOG_1202HY.warning(
                "#1202kc the 'paying without judging a screen' warning is DISABLED "
                "(ENVGEN_NOTHING_SCORED_WARN_USD=%r). This run can spend without ever "
                "scoring a screen and nothing will say so.", _raw_1202kc)
            return None
        root = Path(output_dir)
        usd = None
        try:
            usd = float((json.loads((root / "run_budget.json").read_text(encoding="utf-8"))
                         .get("llm") or {}).get("usd"))
        except Exception:
            return None
        if usd is None or usd < floor:
            return None
        # NOT MEASURED is not the same as judged nothing: a gate file that does not exist
        # yet means the gate has not run, which this must not report as a stalled run.
        try:
            gate = json.loads((root / "design" / "visual_gate" / "gate_state.json")
                              .read_text(encoding="utf-8"))
        except Exception:
            return None
        judged = (gate or {}).get("total_judgments")
        if judged is None or int(judged or 0) > 0:
            return None
        _NOTHING_SCORED_WARNED_1202HY[key] = True
        msg = ("#1202hy this run has spent $%.0f and the visual gate has judged ZERO "
               "screens. The one run that delivered on this corpus had already judged a "
               "screen by $43; two that did not (r102, r106) look exactly like this and "
               "spent $122 and $165 here. Check whether the app boots -- backend_health "
               "and business_endpoints_reachable are the usual reason -- before paying "
               "for more of the same. Warning only; set ENVGEN_NOTHING_SCORED_WARN_USD=0 "
               "to silence." % usd)
        (logger.warning(msg) if logger else None)
        return msg
    except Exception:
        return None


def list_snapshots(output_dir) -> List[Dict]:
    """Newest last. Each entry carries the manifest plus the directory name to restore."""
    out: List[Dict] = []
    root = snapshots_root(output_dir)
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir(), key=_order_key):
        if not d.is_dir() or d.name.startswith("."):
            continue
        rec = {"name": d.name, "kind": _kind_of(d), "files": 0, "bytes": 0}
        try:
            rec.update(json.loads((d / _MANIFEST).read_text(encoding="utf-8")))
        except Exception:
            pass
        rec["name"] = d.name
        rec.update(_snapshot_health_1202di(d))
        rec.update(_snapshot_quality_1202hx(d))
        rec.update(_snapshot_budget_1202ia(d))
        out.append(rec)
    return out


# #1202hx: "WHICH ONE WAS THE GOOD STATE?"
#
# #1202bw stores many restore points and #1202di says whether each one had judged
# anything -- which separates a snapshot of a run that could not boot from one that
# could, and stops there. Neither says which of the ones that DID score is the best
# place to restart, so `--restore-snapshot` is chosen by reading timestamps, and the
# newest is not the best: r106's last interval scored 1 of 9 screens at a 0.34 median
# while an earlier milestone of the same run had judged the same set no worse.
#
# Both numbers are already INSIDE every snapshot -- #1202cs put design/ (JSON only)
# there, which carries visual_gate/gate_state.json and milestone_gates.json. Nothing
# new is captured; the listing simply stops throwing the answer away.
#
# `None` means NOT MEASURED throughout, never coerced to 0, for the same reason #1202di
# gives: a snapshot older than the gate directory has no verdict, which is a different
# fact from "scored nothing".
_VISUAL_PASS_1202HX = 0.65


def _snapshot_quality_1202hx(d: Path) -> Dict:
    """How GOOD was the run here — screens over threshold, median, blocking checks."""
    q: Dict = {"screens_pass": None, "screens_total": None, "visual_med": None,
               "fwval_failed": None, "deliver_stuck": None}
    try:
        gate = json.loads((d / "design" / "visual_gate" / "gate_state.json")
                          .read_text(encoding="utf-8"))
        best = (gate or {}).get("_best_by_screen")
        if isinstance(best, dict) and best:
            scores = []
            for v in best.values():
                sc = v.get("score") if isinstance(v, dict) else v
                try:
                    scores.append(float(sc))
                except (TypeError, ValueError):
                    continue
            if scores:
                scores.sort()
                q["screens_total"] = len(scores)
                q["screens_pass"] = sum(1 for x in scores if x >= _VISUAL_PASS_1202HX)
                q["visual_med"] = scores[len(scores) // 2]
    except Exception:
        pass
    try:
        mg = json.loads((d / "design" / "milestone_gates.json").read_text(encoding="utf-8"))
        if isinstance(mg, dict):
            fs = mg.get("_fwval_failure_set")
            if isinstance(fs, list):
                q["fwval_failed"] = [str(x) for x in fs]
            ds = mg.get("_fwdeliver_stuck_count")
            if ds is not None:
                q["deliver_stuck"] = int(ds or 0)
    except Exception:
        pass
    return q


# #1202ia: A RESTORE POINT IS ONLY WORTH ANYTHING IF THE RUN CAN STILL REACH A GATE.
#
# #1202hx ranks restore points by how good the run LOOKED. It said nothing about whether
# resuming from one can still pay off, and those are different questions: the
# no-convergence abort spends a budget (`ENVGEN_NO_DELIVER_ABORT_S`, lane time since the
# contract was built) that is CUMULATIVE ACROSS EVERY PROCESS over the output dir and is
# carried, correctly, into every snapshot's own ledger.
#
# That accounting is right and must not be "fixed": those minutes were really spent by
# processes that really failed to deliver, and zeroing them would disable the backstop
# that exists because r15 spent 2h50m and r37 spent $371 doing exactly that.
#
# What was missing is saying so at SELECTION time. tiktok-r106: every one of its restore
# points, including the best one #1202hx named, was taken when 79.6 of the run's 90
# minutes were already gone. Restoring the best of them and resuming cost $70.27 and died
# on NO-CONVERGENCE 21 minutes later without reaching a single gate evaluation. The number
# that predicted it was already inside the snapshot -- `cumulative_1202cg.alive_before_
# this_run`, beside the screens the listing was happy to print.
#
# #1202hz warns once the run is under way. This shows the same fact one decision earlier,
# at selection time.
#
# ★ It is a NUMBER, deliberately NOT a verdict. The first draft of this printed "DO NOT
#   RESUME" when the budget was gone, and validating it against the run that DELIVERED
#   killed that idea outright: tiktok-r97 cut release 1.0.0 at 14:11 with its budget
#   already about 52 minutes NEGATIVE, and ran on to -110 without ever aborting. The
#   abort needs BOTH an exhausted budget AND a DECLINED delivery, and r97's deliveries
#   were progressing (4/9 -> 5/9 screens), so the decline stamp kept resetting.
#
#   One death (r106) and one survival (r97) is not a calibration. Print what is known and
#   let the operator judge; a confident wrong verdict here would have talked someone out
#   of the only run on this corpus that ever shipped.
def _abort_budget_s_1202ia() -> float:
    """The no-convergence budget a run gets, as the orchestrator reads it."""
    try:
        return float(os.environ.get("ENVGEN_NO_DELIVER_ABORT_S", "4500") or 4500)
    except (TypeError, ValueError):
        return 4500.0


def _snapshot_budget_1202ia(d: Path) -> Dict:
    """Lane-time budget left at this restore point. `None` when it cannot be read."""
    out: Dict = {"budget_left_s": None, "budget_cap_s": None}
    try:
        _led = json.loads((d / "run_budget.json").read_text(encoding="utf-8"))
        cum = _led.get("cumulative_1202cg") or {}
        # #1202ig: `alive_total`, NOT `alive_before_this_run`.
        #
        # The first cut of this read the "before" figure, which is the time PREVIOUS
        # processes spent and is 0 for a run that has never been resumed. So every one of
        # r107's snapshots was reported "budget 90min left" while the run had been alive
        # 124 minutes — and the framework said so itself the moment a resume started:
        # "#1202fw this run has ALREADY spent 124 min of lane time ... past the 90 min".
        # A tool built to stop a doomed resume was recommending one.
        #
        # `alive_total` (= before + this run's own elapsed) is the quantity the abort
        # actually bounds lane time by, in `_lane_time_1202fk`. Reading anything else here
        # guarantees the listing and the abort disagree.
        spent = cum.get("alive_total")
        if spent is None:
            _before = cum.get("alive_before_this_run")
            _elapsed = (_led.get("usage") or {}).get("elapsed_sec")
            if _before is None and _elapsed is None:
                return out
            spent = float(_before or 0.0) + float(_elapsed or 0.0)
        cap = _abort_budget_s_1202ia()
        out["budget_cap_s"] = cap
        out["budget_left_s"] = round(cap - float(spent), 1)
    except Exception:
        pass
    return out


def best_snapshot_1202hx(snaps: List[Dict]) -> Optional[str]:
    """Name of the snapshot worth restarting from, or None if none can be ranked.

    Ordered by what actually decides whether a restart is ahead or behind: screens over
    threshold, then the median (a run can hold its count while every screen improves),
    then FEWER blocking framework-validation checks, then MORE budget left, then the later
    one. A snapshot that scored nothing is never "best" -- restoring it resumes a run with
    no visual evidence at all, which is exactly the trap #1202di was written about.

    #1202iu: `budget_left_s` was computed, printed in the listing, and described in its own
    call site as "the quality that decides whether restoring is ahead or behind" -- and then
    left out of this key, so the last tiebreaker was "the later one". On r109's real
    snapshots that picked `135712-interval-gate5`: same 0/9 screens, same 0.36 median and
    same single blocking check as `125512-interval-t14`, but $58 further spent and **32
    minutes past the wall** instead of 30 minutes short of it. Restoring it is pure loss --
    identical state, less runway. Evidence recorded and not used is the dominant defect
    shape in this pipeline, and this one was mine.

    Unknown budget ranks at 0.0, the line between ahead and behind: it must not beat a
    measured positive nor lose to a measured negative. Reading a missing value as zero is
    the mistake #902/#907/#566y all were, so it is stated rather than left to `or 0`.
    """
    ranked = [s for s in snaps if s.get("screens_pass") is not None
              and (s.get("judgments") or 0) > 0]
    if not ranked:
        return None
    def key(s: Dict):
        _b = s.get("budget_left_s")
        return (s.get("screens_pass") or 0,
                s.get("visual_med") or 0.0,
                -len(s.get("fwval_failed") or []),
                0.0 if _b is None else float(_b),
                s.get("epoch") or 0.0)
    return max(ranked, key=key).get("name")


def _snapshot_health_1202di(d: Path) -> Dict:
    """Was the run healthy at this snapshot? Read from the snapshot's own files.

    The listing showed name/kind/files/MB — none of which answers the only question an
    operator has while choosing a restore point. netflix-r43 could not boot its app for an
    entire run (first a port clash, next day a full disk), so every snapshot it took was
    inside a poisoned window at `total_judgments: 0`, and restoring any of them continues a
    run that has never scored a screen. Nothing said so at selection time.

    Nothing new is captured: #1202cs already put `design/visual_gate` (JSON only) into the
    snapshot and `run_budget.json` was always there.

    ``None`` means NOT MEASURED and is never coerced to 0 — a snapshot taken before the gate
    directory existed has no verdict, which is a different fact from "judged nothing". That
    conflation is exactly how #1039's dead seed audit read as clean for 2728 attempts.
    """
    health: Dict = {"judgments": None, "plateau": None, "usd": None, "ticks": None}
    try:
        gate = json.loads(
            (d / "design" / "visual_gate" / "gate_state.json").read_text(encoding="utf-8"))
        if isinstance(gate, dict):
            if gate.get("total_judgments") is not None:
                health["judgments"] = int(gate.get("total_judgments") or 0)
            if gate.get("plateau_rounds") is not None:
                health["plateau"] = int(gate.get("plateau_rounds") or 0)
    except Exception:
        pass
    try:
        budget = json.loads((d / "run_budget.json").read_text(encoding="utf-8"))
        if isinstance(budget, dict):
            _usd = (budget.get("llm") or {}).get("usd")
            if _usd is not None:
                health["usd"] = float(_usd)
            _ticks = (budget.get("usage") or {}).get("ticks")
            if _ticks is not None:
                health["ticks"] = int(_ticks)
    except Exception:
        pass
    return health


def restore_snapshot(output_dir, name: str) -> Dict:
    """Copy a snapshot back over the run directory.

    The CURRENT state is copied aside first (``snapshots/.pre-restore-<ts>/``) — restoring
    is the one operation here that destroys state, and an operator who rewinds to the wrong
    point must be able to get back. That safety copy is exempt from pruning (it is not a
    snapshot kind) and is the caller's to delete.

    Returns {"ok": bool, "restored": [...], "backup": str, "error": str}.
    """
    out = Path(output_dir)
    src = snapshots_root(out) / name
    if not src.is_dir():
        return {"ok": False, "restored": [], "backup": "",
                "error": f"no such snapshot: {name}"}

    backup = snapshots_root(out) / f".pre-restore-{time.strftime('%Y%m%d-%H%M%S')}"
    restored: List[str] = []
    try:
        for f in sorted(src.rglob("*")):
            if not f.is_file() or f.name == _MANIFEST:
                continue
            rel = f.relative_to(src)
            live = out / rel
            if live.is_file():
                b = backup / rel
                b.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(live, b)
            live.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, live)
            restored.append(str(rel))
    except Exception as e:
        return {"ok": False, "restored": restored, "backup": str(backup), "error": str(e)}
    return {"ok": True, "restored": restored, "backup": str(backup), "error": ""}
