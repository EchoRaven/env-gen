"""#1202ma — the framework knew which type rejected the value and told a log nobody reads.

GROUND TRUTH (tiktok-web-r121 resume #3): its test-user filed, six times,

    TEST-USER validation: ISSUES — BROKEN: POST /api/feed → 400 ({"detail":"invalid field value"})

`"invalid field value"` is the projected DataError→400 handler. The template's own comment
states the design:

    Response prose is fixed (no DB internals leaked); the driver detail goes to the log the
    owning lane can read.

The first half is a deliberate, defensible rule and is kept. The second half is falsifiable,
and it is false: `docker_logs` was called ZERO times in r117, r119, r120 and r121. Nobody has
ever read that log in any of them, so the one actionable fact — which TYPE rejected the value
— reached nobody, and a lane was handed a category six times.

The hint goes in a SECOND field. `detail` is untouched on purpose: `chain_executor`'s
`_INTEGRITY_BODY_1202GB` matches it as a substring of the body, and a reworded `detail` would
silently break that check.
"""
import ast
import inspect
import io
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import backend_scaffold as bs

_SRC = Path(inspect.getfile(bs)).read_text(encoding="utf-8")


def _emitted_block() -> str:
    """The integrity-mapping template exactly as it is written into main.py."""
    end = _SRC.index("# === end integrity mapping ===")
    start = _SRC.rindex("try:\n    from sqlalchemy.exc import DataError", 0, end)
    return _SRC[start:end + len("# === end integrity mapping ===")]


def _hint():
    block = _emitted_block()
    ns = {}
    k = block.index("def _fw_data_error_hint_1202ma")
    m = block.index("if _FWDataError is not None:")
    exec(block[k:m], ns)
    return ns["_fw_data_error_hint_1202ma"]


def test_the_emitted_template_is_valid_python():
    """★ It is a STRING in this module — the outer file parsing proves nothing about it."""
    ast.parse(_emitted_block())


@pytest.mark.parametrize("orig,want", [
    ('invalid input syntax for type integer: "abc"', "invalid input syntax for type integer"),
    ("value too long for type character varying(50)",
     "value too long for type character varying(50)"),
    ('date/time field value out of range: "13/45/2026"',
     "date/time field value out of range"),
    ("invalid input syntax for type numeric: 'x'", "invalid input syntax for type numeric"),
])
def test_the_type_survives_and_the_value_does_not(orig, want):
    assert _hint()(orig) == want


def test_the_value_is_never_echoed_back():
    """★ The "no DB internals leaked" half of the rule is the half being KEPT."""
    h = _hint()
    for secret in ("hunter2", "ava.chen@example.com", "4111111111111111"):
        assert secret not in h('invalid input syntax for type integer: "%s"' % secret)


def test_it_is_bounded_and_single_line():
    h = _hint()
    assert len(h("x" * 400)) <= 120
    assert "\n" not in h("first line\nsecond line")
    assert h("first line\nsecond line") == "first line"


@pytest.mark.parametrize("junk", [None, "", "   ", 0, object()])
def test_it_never_raises_on_a_failing_path(junk):
    out = _hint()(junk)
    assert isinstance(out, str) and out


def test_detail_is_unchanged_so_the_substring_matcher_still_fires():
    """★ chain_executor._INTEGRITY_BODY_1202GB is matched with `not in str(body)`."""
    from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce
    assert ce._INTEGRITY_BODY_1202GB == "invalid field value"
    block = _emitted_block()
    assert '"detail": "invalid field value"' in block, (
        "the body prose changed — the chain-executor substring check would go silent")


def test_the_hint_is_a_separate_field():
    block = _emitted_block()
    assert '"field_hint": _fw_data_error_hint_1202ma(' in block


def test_the_helper_is_defined_before_it_is_used():
    """★ Reachability inside the EMITTED file, which imports nothing from this package."""
    block = _emitted_block()
    assert block.index("def _fw_data_error_hint_1202ma") < block.index(
        '"field_hint": _fw_data_error_hint_1202ma(')


def test_the_falsified_half_of_the_comment_is_recorded():
    """A claim measured false must not survive as guidance for the next reader."""
    block = _emitted_block()
    i = block.index("def _fw_data_error_hint_1202ma")
    doc = block[i:block.index("if _FWDataError is not None:")]
    assert "docker_logs" in doc and "ZERO" in doc
