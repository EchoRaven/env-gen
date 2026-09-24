"""#1202ca — a resume must not re-buy the compiled reference spec.

compile_reference_spec is one LLM call over every staged reference and document: 2.3M
characters on r35's resume, ~$3 at uncached rates, five seconds into the run. The result is
written to design/reference_spec.json and was then recompiled from scratch on the next
attempt — the same shape #1202bv fixed for design-prep.

Gated on the fingerprint rather than on --resume: when the images, documents and
requirements text are byte-for-byte what produced the spec on disk, compiling it again buys
nothing. LOCAL-ONLY (agent/tests/ gitignored).
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.reference_materials import (  # noqa: E402
    reusable_reference_spec_1202ca, record_reference_spec_input_1202ca)

IMAGES = ["/refs/home.png", "/refs/detail.png"]
DOCS = ["/refs/spec.md"]
REQ = "build a netflix clone"
SPEC = {"screens": [{"name": "home"}], "endpoints": [{"path": "/api/titles"}],
        "entities": [], "mcp_tools": []}


def _lay(tmp_path, spec=SPEC, stamp=True):
    d = tmp_path / "design"
    d.mkdir(parents=True, exist_ok=True)
    (d / "reference_spec.json").write_text(json.dumps(spec), encoding="utf-8")
    if stamp:
        record_reference_spec_input_1202ca(tmp_path, IMAGES, DOCS, REQ)
    return tmp_path


def test_the_same_inputs_reuse_the_spec(tmp_path):
    got = reusable_reference_spec_1202ca(_lay(tmp_path), IMAGES, DOCS, REQ)
    assert got and got["screens"][0]["name"] == "home"


def test_no_spec_on_disk_is_not_reusable(tmp_path):
    assert reusable_reference_spec_1202ca(tmp_path, IMAGES, DOCS, REQ) is None


def test_a_spec_without_a_fingerprint_is_not_reusable(tmp_path):
    """A spec from before this fix records nothing about what compiled it."""
    assert reusable_reference_spec_1202ca(
        _lay(tmp_path, stamp=False), IMAGES, DOCS, REQ) is None


def test_an_edited_brief_forces_a_recompile(tmp_path):
    """The reason the requirements text is hashed rather than ignored."""
    assert reusable_reference_spec_1202ca(
        _lay(tmp_path), IMAGES, DOCS, REQ + " with live chat") is None


def test_a_changed_reference_set_forces_a_recompile(tmp_path):
    assert reusable_reference_spec_1202ca(
        _lay(tmp_path), IMAGES + ["/refs/new.png"], DOCS, REQ) is None


def test_a_dropped_doc_forces_a_recompile(tmp_path):
    assert reusable_reference_spec_1202ca(_lay(tmp_path), IMAGES, [], REQ) is None


def test_reference_order_does_not_force_a_recompile(tmp_path):
    assert reusable_reference_spec_1202ca(
        _lay(tmp_path), list(reversed(IMAGES)), DOCS, REQ) is not None


def test_an_unusable_spec_is_not_resurrected(tmp_path):
    """The caller treats a spec with no screens/endpoints/entities/mcp_tools as nothing;
    reuse must apply the same bar rather than hand back an empty shell."""
    root = _lay(tmp_path, spec={"screens": [], "endpoints": [], "entities": [],
                                "mcp_tools": []})
    assert reusable_reference_spec_1202ca(root, IMAGES, DOCS, REQ) is None


def test_a_corrupt_spec_file_is_not_reusable(tmp_path):
    root = _lay(tmp_path)
    (root / "design" / "reference_spec.json").write_text("{ not json", encoding="utf-8")
    assert reusable_reference_spec_1202ca(root, IMAGES, DOCS, REQ) is None


def test_the_fingerprint_is_written_after_the_spec():
    """A crash between the two must leave a spec with no fingerprint — which reads as
    'recompile'. The reverse order would leave a fingerprint vouching for a spec that was
    never written. #943: landmark anchors, not a byte window."""
    src = (LLM / "multi_agent" / "runtime" / "reference_materials.py").read_text(
        encoding="utf-8")
    w = src.index('spec_path.write_text(json.dumps(spec')
    # Anchor forward from the write: searching for the bare name finds the DEF, which
    # necessarily precedes its own call site and would make this pass for the wrong reason.
    assert "        record_reference_spec_input_1202ca(output_dir" in src[w:]
    assert "        record_reference_spec_input_1202ca(output_dir" not in src[:w]


def test_component_specs_still_run_when_the_spec_is_reused():
    """They carry their own per-image reuse (#1186) and are what MATERIAL-PREP reports;
    skipping them with the spec would silently stop measuring new references."""
    src = (LLM / "multi_agent" / "runtime" / "reference_materials.py").read_text(
        encoding="utf-8")
    i = src.index("_spec_1202ca is not None")
    branch = src[i:src.index("else:", i)]
    assert "precompute_component_specs(" in branch
