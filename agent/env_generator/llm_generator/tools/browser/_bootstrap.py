"""#234 (tiktok r24/r25, live): playwright's browser binaries VANISHED mid-day
(the disk-full cleanup collateral-deleted ~/.cache/ms-playwright/chromium_headless_shell-*)
and every launch for the rest of r24 + ALL of r25 failed with "Executable doesn't
exist" — 102 failures in one run. Because a walk that cannot run reports ran=False
and "infra must never block a release", the #224/#231d runtime DOM holds were
silently BLIND for the whole run, and the verifier "recorded" browser flows it
never drove. A missing executable is not a transient flake: it never self-clears,
so heal it in-process — detect the signature, run ``playwright install`` ONCE per
process, and let the caller retry. Env-agnostic, pure infra.
"""
from __future__ import annotations

# #646 — ONE VIEWPORT. The pipeline had three, and no two agreed:
#
#     visual_fidelity._VIEWPORT     1380x900  (1.533)  <- the one that DECIDES the score
#     test_user_runner._VIEWPORT    1280x800  (1.600)
#     browser/_manager (agent tool) 1280x720  (1.778)  <- what a lane SEES when it checks its work
#
# Measured across the corpus, agents drive that third one **9420 times** — 3347 navigates and
# **1332 explicit screenshots**, i.e. "let me look at what I just built". They were looking at a
# viewport 180px shorter and 100px narrower than the one being scored. This is the session's
# recurring shape once more: the actor's view is not the measurement's view.
#
# Aligned on the gate's value because the gate is what decides. Whether 900 is the RIGHT height
# is a separate, open question (#644 measured the capture at 1.533 against a reference set whose
# median aspect is 1.7344, and parked the change because the two consumers of that number want
# opposite corrections). Making it one constant is what lets that question be answered ONCE.
CANONICAL_VIEWPORT_646 = {"width": 1380, "height": 900}

import contextlib
import logging
import os
import subprocess
import sys
import threading

_LOG = logging.getLogger("tools.browser.bootstrap")

# Playwright's stable missing-binary signature (raised by BrowserType.launch).
_MISSING_SIG = "Executable doesn't exist"

# #1203m2: THE DRIVER RAN OUT OF HEAP, AND THAT IS WHAT KILLED THE BROWSER.
#
# Playwright's driver is a bundled node process -- the protocol bridge, not Chromium -- and
# node's default old-space ceiling applies to it. Measured on the binary this repo resolves
# (`driver/node -e "require('v8').getHeapStatistics().heap_size_limit"`): **4288 MB**, and the
# corpus OOM reports die at 4099 MB used, which is that ceiling.
#
# 30 OOM events across 19 of the 39 modern root logs, every one with
# `playwright/driver/node` in its native stack. The driver's own uptime is printed beside the
# fatal line: min 11.5 min, **median 59 min**, max 200 min -- so this is a long-lived driver
# filling up, and the only driver that lives that long by construction is the shared one this
# package hands to every lane (created once per process, replaced only when it dies).
#
# WHAT IT COSTS, measured rather than assumed. `Connection closed while reading from the
# driver` appears 9 times in the modern corpus and **9 of 9** are preceded by one of these
# OOMs, by 1-4 seconds (one at 89s). That is the error #1199 had to carve out of the product
# verdict ("r26 produced 214 ... 92% of that run's navigation failures") and the one #1198
# rebuilds around -- 44 rebuilds across 21 runs, 0 give-ups. So nothing is misattributed and
# nothing is lost (`browser_navigate` clears the console/network lists on every navigation
# anyway, so the fresh `BrowserState` costs no evidence); what it costs is the in-flight
# operation and the rebuild, twice per run on average.
#
# 8192 MB verified to take effect on the same binary (-> 8384 MB limit) and verified to be
# inherited by the driver playwright actually spawns, read back from its own
# /proc/<pid>/environ. The host has 125 GB with 108 GB free, so the 4 GB default was never a
# host constraint.
#
# ★ SCOPED TO THE SPAWN, NOT THE PROCESS. `NODE_OPTIONS` is inherited by every node started
# afterwards, and the lanes run `npm install` / `npm run build` for the generated app in this
# same process tree. Changing the app's build environment is not this fix's business
# (#1202cw's spirit: the framework does not reach into app work), so the variable is set
# around the driver spawn and restored immediately.
#
# ★ AN OPERATOR'S CHOICE WINS. If NODE_OPTIONS already names --max-old-space-size, it is left
# exactly alone; otherwise ours is appended to whatever is there rather than replacing it.
#
# ★ WHAT THIS DOES NOT DO, stated because the number says so. Time-to-OOM scales with the
# ceiling, so doubling it roughly doubles the median 59 minutes -- it makes the death rarer in
# a 2-4 hour run, it does not remove the cause. The cause is that the driver keeps a handle per
# Request/Response/ConsoleMessage until the context that produced it closes, and this package
# closes its context only when the driver has already died; `_on_response`'s own comment two
# hundred lines below says the same thing about a different consequence ("the verifier's
# context is created once per run and never reset"). Recycling the context on a budget is the
# real fix and it is a BEHAVIOUR change -- a fresh context is logged out, and nothing here
# restores storage state -- so it is not bundled into a resource ceiling. Measured before
# deferring it: the session loss a rebuild already causes has no signature in the corpus
# (auth-ish signals within 120s of the 44 rebuilds: 41/44, against a same-log random-position
# control of 38/44 and the same mean, 10.5 vs 10.1 -- i.e. the base rate).
#
# This does not retire #1198. A driver can still die for other reasons, and it still rebuilds.
_DRIVER_HEAP_MB_1203M2 = 8192


def _driver_heap_mb_1203m2() -> int:
    """The ceiling to ask for, overridable; a non-numeric or <=0 value means "leave it"."""
    raw = os.environ.get("ENVGEN_DRIVER_HEAP_MB")
    if raw is None or not str(raw).strip():
        return _DRIVER_HEAP_MB_1203M2
    try:
        return int(str(raw).strip())
    except Exception:
        _LOG.warning("#1203m2 ENVGEN_DRIVER_HEAP_MB=%r is not a number; using %d MB",
                     raw, _DRIVER_HEAP_MB_1203M2)
        return _DRIVER_HEAP_MB_1203M2


@contextlib.contextmanager
def driver_heap_1203m2():
    """Raise the Playwright driver's V8 heap for a spawn inside this block, and only it."""
    mb = _driver_heap_mb_1203m2()
    prev = os.environ.get("NODE_OPTIONS")
    touched = False
    if mb > 0 and "--max-old-space-size" not in (prev or ""):
        os.environ["NODE_OPTIONS"] = (
            ("%s --max-old-space-size=%d" % (prev, mb)) if prev
            else "--max-old-space-size=%d" % mb)
        touched = True
    try:
        yield
    finally:
        if touched:
            if prev is None:
                os.environ.pop("NODE_OPTIONS", None)
            else:
                os.environ["NODE_OPTIONS"] = prev


_lock = threading.Lock()
_attempted = False


def is_missing_executable(err: object) -> bool:
    """True when a launch failure is the missing-browser-binary class (permanent
    until installed) rather than a transient flake."""
    return _MISSING_SIG in str(err)


def heal_missing_browser(err: object, *, timeout: int = 900) -> bool:
    """If ``err`` is the missing-executable signature, install the playwright
    chromium binaries ONCE per process (idempotent, additive to the shared
    cache — safe while other runs are live). Returns True when an install
    completed and a launch retry is worthwhile; False otherwise. Never raises."""
    global _attempted
    if not is_missing_executable(err):
        return False
    with _lock:
        if _attempted:
            return False
        _attempted = True
    _LOG.error(
        "BROWSER INFRA DOWN: playwright browser binary missing (%s) — every runtime "
        "UI gate (#224/#231d DOM holds, visual gate, browser flows) is blind until "
        "this heals. Attempting one-time `playwright install chromium "
        "chromium-headless-shell`.", str(err)[:200])
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "playwright", "install",
             "chromium", "chromium-headless-shell"],
            capture_output=True, text=True, timeout=timeout)
        if proc.returncode == 0:
            _LOG.warning("BROWSER INFRA HEALED: playwright install completed — "
                         "launch will be retried.")
            return True
        _LOG.error("BROWSER INFRA HEAL FAILED (rc=%s): %s",
                   proc.returncode, (proc.stderr or proc.stdout or "")[-400:])
    except Exception as exc:  # pragma: no cover — heal must never take the caller down
        _LOG.error("BROWSER INFRA HEAL FAILED: %s", exc)
    return False


def reset_for_tests() -> None:
    global _attempted
    with _lock:
        _attempted = False
