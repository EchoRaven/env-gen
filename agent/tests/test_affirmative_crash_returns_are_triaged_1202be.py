r"""#1202be: a handler that returns an AFFIRMATIVE value on crash, triaged by consequence.

#1202ar covered the empty-return shape — a broken check reading as "no problems found".
The inverse is worse: a broken check reading as permission granted, or as a passing
verdict. #1202bd found one of those (framework_may_write failing open over lane work).

This pins the rest of the class. Measured 2026-09-02: 15 functions in llm_generator
return True — or a dict whose pass-like key is literally True — from an exception
handler with no announcement. Every one was read, not classified by its name:

  CONSERVATIVE TOWARD FLAGGING — True means "there IS a problem", so a crash reports
  rather than passes. The safest possible direction.
    _response_has_rows, _reverify_denial_via_fresh_intruder   (both: "keep the leak
    verdict"), _any_blocking_screen_at_bar_1140

  ANSWERING, not measuring
    _is_dark_hex, _env_flag_914 (a flag default), _say_once_925, state_changed_1202ad
    (True = report it, again the safe direction)

  A DELIBERATE BRANCH, not a swallow
    write_py_if_still_parses / _write_py_995 — the `except SyntaxError` there parses the
    OLD file; a file that is already broken is replaced, and True means "wrote it"

  INFRASTRUCTURE PROBES whose false-positive costs a retry, not a verdict
    _is_process_alive, _os_access_w, _reclaim_if_stale, get_branch_status,
    _component_is_rendered_1089

  SILENTLY DEGRADING — fixed by #1202be
    _frontend_rendered — never blocks readiness by design, but said nothing, so a probe
    that fails every time leaves readiness on the weaker "server responded" check for a
    whole run with no line anywhere

An earlier pass counted 20 and included user_gates' `evaluate_gate` and
`_eval_file_exists`. Both are FINE — they return `{"passed": False}` — and the detector
had matched the KEY NAME rather than its value. That is the same mistake this repo's own
seed_audit made, and it is why the count here is checked by value.

It is a CEILING, not a list: bringing one under an announcement lowers it.
"""
import ast
import re
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
_ROOT = THIS_DIR.parent / "env_generator" / "llm_generator"
sys.path.insert(0, str(_ROOT))

_ANNOUNCES = re.compile(
    r"warn_once_1201|_gate_absent_792|_swallowed_79\d|_not_measured_\d+|degraded"
    r"|logger\.(warning|error)|_logger\.(warning|error)")
_PASSLIKE = re.compile(r"ok|clean|pass|valid|success|healthy", re.I)

_CEILING = 14   # 15 measured, minus _frontend_rendered which #1202be announced


_CACHE = {}


def _affirmative_crash_returns():
    """Parses every module in the package, so the result is cached: two tests ask for it
    and the second scan cost ~70s of suite time for a byte-identical answer."""
    if _CACHE:
        return _CACHE["r"]
    found = {}
    for f in _ROOT.rglob("*.py"):
        if "/tests/" in str(f) or "bundled_tests" in str(f):
            continue
        try:
            src = f.read_text(encoding="utf-8")
            tree = ast.parse(src)
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            seg = ast.get_source_segment(src, node) or ""
            if _ANNOUNCES.search(seg):
                continue
            for handler in [h for h in ast.walk(node) if isinstance(h, ast.ExceptHandler)]:
                for stmt in handler.body:
                    if not isinstance(stmt, ast.Return):
                        continue
                    v = stmt.value
                    hit = isinstance(v, ast.Constant) and v.value is True
                    if isinstance(v, ast.Dict):
                        for k, val in zip(v.keys, v.values):
                            # by VALUE, not by key name — an earlier pass flagged
                            # `{"passed": False}` because the word "pass" appeared
                            if (isinstance(k, ast.Constant) and isinstance(k.value, str)
                                    and _PASSLIKE.search(k.value)
                                    and isinstance(val, ast.Constant) and val.value is True):
                                hit = True
                    if hit:
                        found.setdefault(node.name, str(f))
    _CACHE["r"] = found
    return found


def test_the_detector_still_sees_the_class():
    """Guard the guard: an empty result must mean 'none left', not 'scan broke'."""
    found = _affirmative_crash_returns()
    assert len(found) >= 5, f"the scan found only {len(found)}; it is probably broken"


def test_the_count_does_not_grow():
    found = _affirmative_crash_returns()
    assert len(found) <= _CEILING, (
        "a function swallows an exception and returns an affirmative value with no "
        "announcement, so a crashed check now reads as a pass or a permission. Announce "
        "it, or return a value the caller can tell apart from a real answer. New: "
        + "; ".join(f"{n} ({p})" for n, p in sorted(found.items())))


def test_the_readiness_probe_announces_its_degradation():
    """#1202be's own fix, pinned: it may still degrade, but not in silence."""
    src = (_ROOT / "multi_agent/runtime/test_user_runner.py").read_text(encoding="utf-8")
    i = src.index("#1202be")
    j = src.index("return True", i)
    assert "warn_once_1201" in src[i:j]
