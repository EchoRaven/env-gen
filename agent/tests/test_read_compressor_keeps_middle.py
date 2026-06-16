"""ToolResultCompressor must NOT drop the MIDDLE of a large `read` result.

The prior `read` rule was head_tail @ 2000 chars: it kept head+tail and replaced
the middle with "... omitted ...". For a source file (e.g. a 446-line FastAPI
main.py) the route/function bodies live in that dropped middle, so the model saw
an empty-looking shell -> the orchestrator's "all endpoints return empty dicts"
mis-diagnosis and re-read/flail loops. The real per-tool-result budget is the
downstream hard clip in step_pipeline/tooling.py (max_result_len = 16000); the
compressor must defer to it, not destructively pre-empt it at 2000.

This locks in: a large `read` (and the `default` strategy) keeps a CONTIGUOUS
span that still contains a middle marker, bounded by the downstream clip.
"""

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))

from env_generator.llm_generator.multi_agent.context_management import (  # noqa: E402
    ToolResultCompressor,
)

# Keep the test honest about the source of truth for the clip.
CLIP = ToolResultCompressor.DOWNSTREAM_CLIP_CHARS  # 16000


def _file_with_middle_marker(total_chars: int) -> str:
    """A code-file-like blob whose UNIQUE marker sits squarely in the middle."""
    marker = "\nMIDDLE_ROUTE_BODY_MARKER_42\n"
    half = (total_chars - len(marker)) // 2
    return ("HEAD\n" + "a = 1\n" * (half // 6))[:half] + marker + ("b = 2\n" * (half // 6))[:half]


def test_read_keeps_middle_marker_and_is_bounded():
    text = _file_with_middle_marker(total_chars=14000)  # > 10000, < CLIP
    assert "MIDDLE_ROUTE_BODY_MARKER_42" in text  # sanity: marker is in the middle

    out = ToolResultCompressor().compress("read", text, success=True)

    # The middle must survive (this is the whole bug): contiguous head, no drop.
    assert "MIDDLE_ROUTE_BODY_MARKER_42" in out
    assert "chars omitted" not in out  # head_tail's dropped-middle banner is gone
    assert len(out) <= CLIP + 64  # bounded by clip (+head-strategy banner slack)


def test_read_above_clip_is_capped():
    # Larger than the clip -> still bounded (cost guard), still keeps a leading span.
    text = _file_with_middle_marker(total_chars=CLIP * 2)
    out = ToolResultCompressor().compress("read", text, success=True)
    assert len(out) <= CLIP + 64
    assert out.startswith("HEAD")


def test_default_strategy_truncates_contiguously_without_dropping_middle():
    # Unknown tool -> `default` rule (intentionally small at 1000, see
    # test_inbox_no_content_truncation). The point here is the STRATEGY: it keeps
    # a contiguous leading span and never drops the middle (no "chars omitted"
    # head_tail banner), unlike the old `read` rule. Anything past the contiguous
    # head is dropped from the END, not punched out of the middle.
    default_cap = ToolResultCompressor.COMPRESSION_RULES["default"]["max_chars"]
    head_text = "HEADSTART_" + "z" * (default_cap * 2)
    out = ToolResultCompressor().compress("some_unknown_tool", head_text, success=True)
    assert out.startswith("HEADSTART_")        # contiguous leading span preserved
    assert "chars omitted" not in out          # not a middle-dropping head_tail
    assert len(out) <= default_cap + 8         # bounded ("..." suffix slack)
