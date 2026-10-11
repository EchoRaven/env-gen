"""#1203hq — the success banner congratulated 89 of the 93 runs that printed it.

`EventType.GENERATION_COMPLETE` is emitted unconditionally in the orchestrator's finalize
block, with `{"success": success}`. Neither renderer read `success`, so a run that aborted
without delivery ended on `🎉 Generation Complete!` in green. MEASURED over every log on
disk: 93 print the banner, **89 have `Status: FAILED` two lines lower**, and all 89 also
report `📁 0 files generated` and `⏱️  0.0 seconds`.

r178 is the live one — stuck_abort after 33 coordination ticks, $339.72, 10253.7s:

    🎉 ====  Generation Complete!   📁 0 files generated   ⏱️  0.0 seconds
    ...
    Status: FAILED   Cost: $339.72   Duration: 10253.7s

Three false statements. The zeros are the second half: `total_files` is passed by no
emitter and `duration` was passed only inside the message string, so `.get(..., 0)`
printed a confident zero for both. A number the framework does not have is not reported
as zero.
"""

import ast
import datetime
import inspect
import io
import contextlib

import pytest

from env_generator.llm_generator import progress as _pg
from env_generator.llm_generator.progress import ConsoleListener, Event, EventType


def _render(data):
    ev = Event(type=EventType.GENERATION_COMPLETE, message="Done in 10253.7s",
               data=data, timestamp=datetime.datetime.now())
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ConsoleListener()(ev)
    return buf.getvalue()


# --- the banner reads the verdict it was always handed ------------------------------

def test_a_failed_run_is_not_congratulated():
    out = _render({"success": False, "duration": 10253.7})
    assert "Generation Complete!" not in out, out
    assert "FAILED" in out, out
    assert "\U0001F389" not in out, out          # 🎉


def test_a_successful_run_still_is():
    out = _render({"success": True, "duration": 500.0})
    assert "Generation Complete!" in out, out
    assert "FAILED" not in out, out


def test_an_unknown_verdict_keeps_the_old_wording():
    """`success` absent means a caller that predates the field; do not call it a failure."""
    out = _render({"duration": 12.0})
    assert "Generation Complete!" in out, out
    assert "FAILED" not in out, out


# --- numbers the framework does not have are not reported as zero -------------------

def test_a_missing_file_count_is_omitted_not_printed_as_zero():
    out = _render({"success": False, "duration": 10253.7})
    assert "files generated" not in out, out


def test_a_known_file_count_is_printed():
    out = _render({"success": False, "duration": 1.0, "total_files": 7})
    assert "7 files generated" in out, out


def test_the_real_duration_reaches_the_banner():
    out = _render({"success": False, "duration": 10253.7})
    assert "10253.7 seconds" in out, out


def test_a_missing_duration_is_omitted_not_printed_as_zero():
    out = _render({"success": False})
    assert "seconds" not in out, out


# --- the emitter actually supplies the duration -------------------------------------

def test_the_emitter_puts_the_duration_in_the_data_not_only_the_message():
    """★ THE SECOND HALF OF THE DEFECT. The orchestrator computed `duration` and spent it
    on the message string; both renderers read it from `data`."""
    from env_generator.llm_generator.multi_agent import orchestrator as _orch
    src = inspect.getsource(_orch)
    i = src.index("EventType.GENERATION_COMPLETE")
    # Landmark anchors, not a byte window (#943): the emit() call ends at its own closing
    # paren on a line of its own, which is also where the `except` that follows begins.
    j = src.index("            except Exception", i)
    block = src[i:j]
    assert '"duration": duration' in block, block
    assert '"success": success' in block, block


# --- both renderers, because there are two --------------------------------------------

def test_both_renderers_read_the_verdict():
    """★ `grep -c` first: GENERATION_COMPLETE is rendered in TWO classes in this module,
    and patching one would have left the other congratulating failures."""
    src = inspect.getsource(_pg)
    # Count RENDERERS, not every mention: `ICONS` has a `GENERATION_COMPLETE:` entry too,
    # and matching the bare string with a colon counted that map as a third renderer.
    assert src.count("elif event.type == EventType.GENERATION_COMPLETE:") == 2, (
        src.count("elif event.type == EventType.GENERATION_COMPLETE:"))
    tree = ast.parse(src)
    handlers = []
    for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
        for fn in [n for n in cls.body if isinstance(n, ast.FunctionDef)]:
            body = ast.unparse(fn)
            if "EventType.GENERATION_COMPLETE" in body:
                handlers.append((cls.name, body))
    assert len(handlers) == 2, [h[0] for h in handlers]
    for name, body in handlers:
        seg = body[body.index("EventType.GENERATION_COMPLETE"):]
        seg = seg[:seg.index("elif event.type")] if "elif event.type" in seg else seg
        assert "success" in seg, (name, seg[:300])
        assert 'get(\'total_files\', 0)' not in seg and 'get("total_files", 0)' not in seg, (
            name, seg[:300])


def test_the_text_logger_also_says_failed(tmp_path):
    """★ Found by mutation: asserting `"success" in <source>` only proves the NAME is
    there. `_what = "COMPLETE!"` with the lookup left above it passed that check. Render
    the second renderer and read what it wrote."""
    p = tmp_path / "run.txt"
    lg = _pg.RealTimeTextLogger(str(p))
    ev = Event(type=EventType.GENERATION_COMPLETE, message="Done in 10253.7s",
               data={"success": False, "duration": 10253.7},
               timestamp=datetime.datetime.now())
    lg(ev)
    out = p.read_text()
    assert "FAILED" in out, out
    assert "COMPLETE!" not in out, out
    assert "10253.7s" in out, out


def test_the_text_logger_still_celebrates_a_real_success(tmp_path):
    p = tmp_path / "run.txt"
    lg = _pg.RealTimeTextLogger(str(p))
    ev = Event(type=EventType.GENERATION_COMPLETE, message="Done in 12.0s",
               data={"success": True, "duration": 12.0, "total_files": 4},
               timestamp=datetime.datetime.now())
    lg(ev)
    out = p.read_text()
    assert "COMPLETE!" in out and "FAILED" not in out, out
    assert "4 files" in out and "12.0s" in out, out


def test_it_never_raises_on_a_junk_duration():
    out = _render({"success": True, "duration": "not a number"})
    assert out  # rendered something rather than exploding
