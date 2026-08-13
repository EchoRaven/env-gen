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

import logging
import subprocess
import sys
import threading

_LOG = logging.getLogger("tools.browser.bootstrap")

# Playwright's stable missing-binary signature (raised by BrowserType.launch).
_MISSING_SIG = "Executable doesn't exist"

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
