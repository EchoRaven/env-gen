"""#1203r8 -- a pre-registered criterion that can never fire is a defect, not a null result.

`scripts/verify_1020.py` reported `#1203ov` as NOT MEASURED on every run, and the reason was
the check, not the data: it looked for `auth_steps_1203ov` in `test_user_reports/*.json`, and
that key appears ZERO times across 188 such files in 107 runs. Neither does `"auth_ok"` -- the
walkthrough's structured verdict is never persisted. What lands in `report["ui"]` is a digest
(`ran` / `screens` / `top_issues` / `reason`), and that `reason` belongs to the VISUAL GATE,
whose only corpus values are judge failures ("no screenshots or no llm", RateLimitError,
JSONDecodeError). So the check was condemned to print NOT MEASURED forever while looking
diligent -- the same class as the audit that forgot `--log` and read five criteria as "nothing
measured".

It now reads the key #1203ov actually emits, `auth_walk_recorded_no_steps`, whose consumer
sits in the same module. 0 today is CORRECTLY WAITING: the branch needs an auth walk that
recorded nothing, r191 died of exactly that before the fix existed, and r46 -- the only run
since -- authenticated fine.

The companion case is `#1203md`, whose needle is 0 across 455 logs while `SEED SHORTFALL` --
the prefix of the same sentence -- appears 12 times, every one a LANE GREPPING FOR IT. Match
the marker name and those 12 read as proof the mechanism fires; match the emitted sentence and
the truth is zero sightings.

These tests exist because nothing covered that script, which is exactly how a criterion sits
dead without anybody noticing.
"""
import importlib.util
import inspect
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "verify_1020.py"


def _mod():
    spec = importlib.util.spec_from_file_location("verify_1020", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _verdicts(logtext, tmp_path):
    m = _mod()
    m.OUT.clear()
    (tmp_path / "test_user_reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "test_user_reports" / "r.json").write_text('{"summary": {}}', encoding="utf-8")
    m.check_reports(tmp_path, logtext)
    return {t: v for t, v, _d in m.OUT}


def test_the_criterion_fires_when_its_observable_appears(tmp_path):
    """★ THE COUNTER-PROOF, and the whole point. Repointing a dead check at a different
    place is worthless unless the new place can actually produce a sighting."""
    v = _verdicts("... browser gate deferring: auth_walk_recorded_no_steps=True ...", tmp_path)
    assert v.get("#1203ov") == "CONFIRMED", v


def test_it_stays_not_measured_when_the_observable_is_absent(tmp_path):
    """0 is correctly waiting, never CONFIRMED -- #883: do not dress absence as either answer."""
    v = _verdicts("nothing of interest here", tmp_path)
    assert v.get("#1203ov") == "NOT MEASURED", v


def test_it_does_not_read_the_artifact_that_never_holds_the_key():
    """The old spelling. `auth_steps_1203ov` in `test_user_reports/*.json` is 0 for 188 files
    across 107 runs, so a check keyed on it cannot fire -- asserted on the AST of the call so
    a mention of the name in the explanatory comment cannot satisfy it."""
    import ast
    src = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "check_reports")
    # every `say("#1203ov", ...)` must take its count from the LOG, not from the file loop
    says = [n for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and getattr(n.func, "id", "") == "say"
            and n.args and isinstance(n.args[0], ast.Constant)
            and n.args[0].value == "#1203ov"]
    assert len(says) == 1, "expected exactly one #1203ov verdict, got %d" % len(says)
    # Inspect the VERDICT EXPRESSION, not a dump of the whole call. The first version of
    # this assertion searched `ast.dump(...)` for "steps" and was satisfied by the message's
    # own prose ("recorded NO steps") -- a text assertion fed by the text it guards, which is
    # the trap this whole session has been closing. The verdict is `"CONFIRMED" if X else
    # "NOT MEASURED"`, so X is the only thing worth asserting on.
    verdict = says[0].args[1]
    assert isinstance(verdict, ast.IfExp), (
        "expected a conditional verdict, got %s" % type(verdict).__name__)
    names = {n.id for n in ast.walk(verdict.test) if isinstance(n, ast.Name)}
    assert "_ov" in names, (
        "the verdict is not driven by the log-derived count; it tests %s" % sorted(names))
    assert "steps" not in names, (
        "the verdict still tests the per-file `steps` counter, which can never be non-zero")


def test_the_log_only_needle_is_the_emitted_sentence_not_the_marker():
    """#1203md: `SEED SHORTFALL` appears 12 times and every one is a lane grepping for it.
    The needle must be the part of the sentence a grep command would not contain."""
    src = SCRIPT.read_text(encoding="utf-8")
    i = src.index("def check_log_only")
    body = src[i:]
    assert 'r"table\\(s\\) hold fewer rows"' in body, (
        "the #1203md needle must stay the emitted sentence, not `SEED SHORTFALL`")


# ===================================================== the companion: an ABSENT artifact
# `verify_shipped_fixes.py` printed "this file cannot tell them apart -- read the run log for
# the ticket id to decide", and then did not read a log it already held (it is given the run
# directory, and the log is `<run>/logs/*.log`).
#
# These reporters write ONLY when they have findings, and announce through `warn_once_1201`
# when they cannot measure. So an absent artifact is two different answers, and the code
# leaves a sentence for one of them. Measured for #1202zb: the artifact exists in 0 of 107
# runs -- which next to siblings firing in 15-38 runs each reads like a reporter that shipped
# disabled -- while the announcement appears in exactly 3 runs. `warn_once_1201` speaks once
# per process, so 3 runs could not measure and SAID so and 104 measured and found nothing.
#
# The corpus cannot exercise the announcing branch, because those 3 runs keep their logs at
# the repo root rather than under `<run>/logs/`. So both directions are driven by hand.
SHIPPED = ROOT / "scripts" / "verify_shipped_fixes.py"


def _shipped():
    spec = importlib.util.spec_from_file_location("verify_shipped_fixes", SHIPPED)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _zb_verdict(tmp_path, logline=None):
    m = _shipped()
    m._RUNLOG_CACHE_1203R8.clear()
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
    if logline is not None:
        (tmp_path / "logs" / "generation.log").write_text(logline, encoding="utf-8")
    out = []
    m._say = lambda ticket, verdict, headline, detail="": out.append((ticket, verdict)) or verdict
    m.check_1202zb(tmp_path)
    return out[0][1] if out else None


def test_an_absent_artifact_with_no_announcement_is_a_finding_of_zero(tmp_path):
    m = _shipped()
    assert _zb_verdict(tmp_path, "nothing interesting here\n") == m.CONFIRMED


def test_an_absent_artifact_WITH_the_announcement_stays_unmeasured(tmp_path):
    """★ THE COUNTER-PROOF. Without this, the new branch would read every absent artifact as
    a finding of zero -- turning the exact silence-as-a-pass that #1202z5 fixed back on."""
    m = _shipped()
    line = ("12:00:00 [W] multi_agent.runtime.message_format: #1201 the unreachable-twin-table "
            "check could not run (no live row counts from this validation cycle)\n")
    assert _zb_verdict(tmp_path, line) == m.UNMEASURED


def test_with_no_log_on_disk_the_old_ambiguity_stands(tmp_path):
    """Silence alone must never be promoted: with no log there is nothing to decide from,
    and three of the corpus's runs are in exactly that state (their logs sit at the repo
    root, not under the run)."""
    m = _shipped()
    assert _zb_verdict(tmp_path, None) == m.UNMEASURED
