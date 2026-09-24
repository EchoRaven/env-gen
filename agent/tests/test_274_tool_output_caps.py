"""#274 — cap read()'s output by CHARACTERS, not only by lines.

Measured on r59 (opus-4.7, 146 min): the run's cost is almost entirely prompt and the
per-step growth is tool OUTPUT. read was ~1.1M chars over the run. It caps at MAX_READ_LINES
(2000) LINES but not CHARACTERS, so a 2000-line file of very long lines (a minified bundle,
a one-line JSON, one of our own giant projected handlers) still returns megabytes into the
step context. Bound the character size too, on a line boundary, with a pointer to continue
via read(offset=...). Env override ENVGEN_MAX_READ_CHARS. Information-preserving: the tail is
a second read at an offset, not lost.

NOTE deliberately NOT touched: check_inbox bodies. A 2026-06-01 directive
("不要截断，这个肯定要完整信息的") removed a [:500] inbox cap that wedged Facebook-scale
task_ready — the orchestrator passes a multi-thousand-char CONTRACT through the inbox and a
trimmed body left the receiver unable to see it or ask for the rest. test_inbox_no_content_
truncation locks that in; oversized inbox savings must come from the SENDER, not from
clipping on read.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from env_generator.llm_generator.tools.canonical_file_tools.shared import (  # noqa: E402
    MAX_READ_CHARS,
    cap_read_content,
)


def test_small_content_is_unchanged():
    c = "line1\nline2\n"
    assert cap_read_content(c)[0] == c


def test_oversized_content_is_capped_with_a_pointer():
    c = "z" * (MAX_READ_CHARS * 3)
    capped, truncated = cap_read_content(c)
    assert truncated is True
    assert len(capped) <= MAX_READ_CHARS + 300
    assert "offset" in capped.lower() or "truncat" in capped.lower()


def test_cap_falls_on_a_line_boundary_when_possible():
    c = "\n".join("a" * 100 for _ in range(MAX_READ_CHARS // 50))
    capped, truncated = cap_read_content(c)
    assert truncated is True
    body = capped.split("\n… ")[0] if "\n… " in capped else capped
    assert not body.endswith("aa" * 60)


def test_a_2000_line_file_of_long_lines_is_bounded():
    """The exact hole: line count is fine, characters are not."""
    c = "\n".join("x" * 10_000 for _ in range(2000))   # 20M chars, within the 2000-line cap
    capped, truncated = cap_read_content(c)
    assert truncated is True
    assert len(capped) <= MAX_READ_CHARS + 300


def test_empty_and_none_are_safe():
    assert cap_read_content("")[0] == ""
    assert cap_read_content(None)[0] in ("", None)


def test_cap_is_a_pure_function():
    c = "q" * (MAX_READ_CHARS * 2)
    assert cap_read_content(c) == cap_read_content(c)


def test_env_override_respected(monkeypatch):
    """A run can widen/narrow the cap without a code change."""
    import importlib
    from env_generator.llm_generator.tools.canonical_file_tools import shared
    monkeypatch.setenv("ENVGEN_MAX_READ_CHARS", "8000")
    importlib.reload(shared)
    capped, truncated = shared.cap_read_content("w" * 20000)
    assert truncated and len(capped) <= 8000 + 300
    monkeypatch.delenv("ENVGEN_MAX_READ_CHARS", raising=False)
    importlib.reload(shared)
