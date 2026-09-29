r"""#1202z1: the launch script's key file must not overwrite THIS launch's budget.

`scripts/tiktok_designinput.sh` sources `$ENVGEN_KEY_FILE` unconditionally. That file's job
is credentials and prices -- but it also exports `ENVGEN_MAX_SPEND_USD`, so a launcher that
set a cap for this run silently got the key file's number instead.

Caught live, not by reading: r141 was launched with `ENVGEN_MAX_SPEND_USD=450` against a
remaining budget of roughly $880, and `/proc/<pid>/environ` came back with 900. The only
reason it was noticed is that the launcher reads the environment back after starting; every
launch before it believed a cap it had not got.

Same family as #1202wz (three providers reached no spend cap at all). A cap that does not
hold is worse than no cap, because it is believed.

★ The restore ANNOUNCES. A silent restore would be the mirror image of the defect -- the
caller would get its number and never learn the key file disagreed, which is the same
"nobody was told" shape this whole ticket series is about.

★ NON-VACUITY. These tests execute the real blocks cut out of the real script, and assert
that the cut actually contains the `source` line -- an extraction that silently missed it
would leave the caller's value untouched for the wrong reason and pass.
"""
import os
import re
import subprocess
import textwrap

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPT = os.path.join(_ROOT, "scripts", "tiktok_designinput.sh")

_BASH = "/bin/bash"


def _blocks() -> str:
    """The capture block, the `source`, and the restore block -- from the real script."""
    src = open(_SCRIPT, encoding="utf-8").read()
    start = src.index("# #1202z1: THE CALLER'S BUDGET SURVIVES THE KEY FILE.")
    end = src.index('export "$_k1202z1=$_v1202z1"', start)
    end = src.index("\n", end) + 1
    end = src.index("done", end) + len("done")
    return src[start:end]


def test_the_extraction_actually_contains_the_source():
    """★ Without this, every test below would pass by never overwriting anything."""
    b = _blocks()
    assert 'source "${ENVGEN_KEY_FILE}"' in b, b[:400]
    assert "_CALLER_BUDGET_1202Z1" in b


def _run(env_overrides, key_file_body):
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as fh:
        fh.write(key_file_body)
        keyf = fh.name
    script = textwrap.dedent("""
        set -u
        export ENVGEN_KEY_FILE=%s
        %s
        printf 'SPEND=%%s\\nWALL=%%s\\nTICKS=%%s\\n' \\
          "${ENVGEN_MAX_SPEND_USD:-unset}" "${ENVGEN_MAX_WALLCLOCK_SEC:-unset}" \\
          "${ENVGEN_MAX_TICKS:-unset}"
    """) % (keyf, _blocks())
    env = dict(os.environ)
    for k in ("ENVGEN_MAX_SPEND_USD", "ENVGEN_MAX_WALLCLOCK_SEC", "ENVGEN_MAX_TICKS",
              "ENVGEN_DELIVERY_OVERSHOOT", "ENVGEN_CONVERGING_OVERSHOOT"):
        env.pop(k, None)
    env.update(env_overrides)
    out = subprocess.run([_BASH, "-c", script], capture_output=True, text=True, env=env)
    os.unlink(keyf)
    assert out.returncode == 0, out.stderr
    vals = dict(re.findall(r"^(SPEND|WALL|TICKS)=(.*)$", out.stdout, re.M))
    return vals, out.stdout


_KEY_WITH_CAP = "export ENVGEN_MAX_SPEND_USD=900\nexport ENVGEN_MODEL=x\n"


def test_the_caller_wins():
    """The live case: 450 asked for, 900 in the key file."""
    vals, _ = _run({"ENVGEN_MAX_SPEND_USD": "450"}, _KEY_WITH_CAP)
    assert vals["SPEND"] == "450", vals


def test_the_override_is_announced():
    """★ A silent restore would repeat the defect from the other side."""
    _, out = _run({"ENVGEN_MAX_SPEND_USD": "450"}, _KEY_WITH_CAP)
    assert "#1202z1" in out and "900" in out and "450" in out, out


def test_a_caller_that_asks_for_nothing_still_gets_the_key_files_value():
    """No regression: the key file remains the default for a launch that sets no cap."""
    vals, out = _run({}, _KEY_WITH_CAP)
    assert vals["SPEND"] == "900", vals
    assert "#1202z1" not in out, "nothing was overridden, so nothing should be announced"


def test_an_agreeing_key_file_says_nothing():
    vals, out = _run({"ENVGEN_MAX_SPEND_USD": "900"}, _KEY_WITH_CAP)
    assert vals["SPEND"] == "900"
    assert "#1202z1" not in out, out


def test_a_knob_the_key_file_never_mentions_passes_through():
    vals, _ = _run({"ENVGEN_MAX_WALLCLOCK_SEC": "9000"}, _KEY_WITH_CAP)
    assert vals["WALL"] == "9000", vals


@pytest.mark.parametrize("knob,val", [
    ("ENVGEN_MAX_SPEND_USD", "123"),
    ("ENVGEN_MAX_WALLCLOCK_SEC", "456"),
    ("ENVGEN_MAX_TICKS", "78"),
])
def test_every_budget_knob_is_protected(knob, val):
    """★ Not just the one that bit. A key file that grows a wall-clock or tick default
    tomorrow must not silently take those either."""
    body = "export %s=999999\nexport ENVGEN_MODEL=x\n" % knob
    vals, _ = _run({knob: val}, body)
    key = {"ENVGEN_MAX_SPEND_USD": "SPEND", "ENVGEN_MAX_WALLCLOCK_SEC": "WALL",
           "ENVGEN_MAX_TICKS": "TICKS"}[knob]
    assert vals[key] == val, vals


def test_the_script_still_parses():
    out = subprocess.run([_BASH, "-n", _SCRIPT], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


def test_the_capture_runs_before_the_source():
    """Order is the whole mechanism: capturing after the source would capture the key
    file's value and 'restore' it over the caller's."""
    src = open(_SCRIPT, encoding="utf-8").read()
    assert (src.index("_CALLER_BUDGET_1202Z1=\"\"")
            < src.index('source "${ENVGEN_KEY_FILE}"')
            < src.index("for _kv1202z1 in $_CALLER_BUDGET_1202Z1"))
