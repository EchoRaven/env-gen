"""#267/#268 — two rules borrowed from Hatch's memory engine, measured against ours.

Measured on r57's real memory bank (8 lanes x 6 files, ~47 KB): ZERO lines carry any
provenance — no ``path:line``, no ``src:``, nothing. Anything a lane writes becomes durable
context every later lane reads as established fact, with no way to tell a measurement from
a guess.

That is the same defect class that cost this session roughly six runs: an LLM's unsourced
verdict erasing a measured PASS (#254/#258), an unsourced chain variable resolving to a
foreign id (#263), an unwinnable denial probe (#266). Hatch collapses all of it into one
rule — no citation, no promotion; it can only ever be a hypothesis — and that rule is worth
more here than any single one of those patches.

#268 classifies at READ time only. Write-time rejection would drop content mid-run and the
lane would never learn why; labelling lets the reader weigh it, which is exactly Hatch's
Promote / Hypothesis split.

#267 is the cheap half: Hatch only rewrites a bank when the content actually changed. Ours
writes unconditionally, so an identical update still rewrites the file, changes its mtime,
and — because these files are injected into prompts — moves bytes in the prompt prefix. Same
prompt-cache concern as #255, in a second place.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from env_generator.llm_generator.memory.memory_bank import (  # noqa: E402
    MemoryFile,
    classify_memory_line,
)


# ---------------------------------------------------------------- #268 classify
def test_file_and_line_is_sourced():
    for line in ("fixed in app/backend/custom_routes.py:338",
                 "see agent/utils/llm.py:1268 for the wire contract",
                 "- broken at src/main.tsx:12-40"):
        assert classify_memory_line(line) == "sourced", line


def test_hub_record_names_count_as_sources():
    """Our provenance is not only files — a hub check/endpoint id is just as verifiable."""
    for line in ("validation:ui_flow:explore is green",
                 "registered GET /api/videos/{id}",
                 "check build:docker passed"):
        assert classify_memory_line(line) == "sourced", line


def test_bare_assertions_are_hypotheses():
    for line in ("the frontend is probably fine now",
                 "I think the seed data is broken",
                 "auth works"):
        assert classify_memory_line(line) == "hypothesis", line


def test_structure_and_blank_lines_are_neutral():
    for line in ("", "   ", "# Progress", "## Current Focus", "---", "```"):
        assert classify_memory_line(line) == "structure", repr(line)


def test_r57_regression_a_whole_uncited_bank_reads_as_hypotheses():
    """The exact shape measured in r57: prose progress notes, no provenance anywhere."""
    body = ["# Progress", "", "## Completed",
            "- Implemented the video feed endpoint",
            "- Auth flow is working end to end", ""]
    kinds = [classify_memory_line(l) for l in body]
    assert kinds.count("sourced") == 0
    assert kinds.count("hypothesis") == 2


def test_a_mixed_bank_separates_cleanly():
    body = ["## Completed",
            "- feed endpoint added in app/backend/custom_routes.py:278",
            "- everything else looks good"]
    kinds = [classify_memory_line(l) for l in body]
    assert kinds == ["structure", "sourced", "hypothesis"]


# ---------------------------------------------------------------- #267 stable render
def test_identical_content_is_not_rewritten(tmp_path):
    f = MemoryFile(name="progress", path=tmp_path / "progress.md")
    f.save("# Progress\n- a\n")
    first = f.path.stat().st_mtime_ns
    f.save("# Progress\n- a\n")
    assert f.path.stat().st_mtime_ns == first, "an unchanged save must not touch the file"


def test_changed_content_is_written(tmp_path):
    f = MemoryFile(name="progress", path=tmp_path / "progress.md")
    f.save("# Progress\n- a\n")
    f.save("# Progress\n- a\n- b\n")
    assert f.path.read_text() == "# Progress\n- a\n- b\n"


def test_first_write_always_lands(tmp_path):
    f = MemoryFile(name="progress", path=tmp_path / "sub" / "progress.md")
    f.save("# Progress\n")
    assert f.path.exists() and f.path.read_text() == "# Progress\n"


def test_unchanged_save_still_refreshes_in_memory_state(tmp_path):
    """Skipping the WRITE must not skip the bookkeeping the caller relies on."""
    f = MemoryFile(name="progress", path=tmp_path / "progress.md")
    f.save("x")
    f.content = "stale"
    f.save("x")
    assert f.content == "x"
