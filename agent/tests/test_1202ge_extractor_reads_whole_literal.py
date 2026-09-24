"""#1202ge — the frontend-call extractor must read a path literal whole.

The old pattern was `(/[^`'"]+)`: a path is "anything that is not a quote". A template
literal whose interpolation contains a NESTED template breaks that, and the generated
api.js writes exactly one:

    fetch(`/api/search${qs ? `?${qs}` : ''}`)

The capture stopped at the inner backtick and produced `/api/search${qs ? ` — half an
expression, handed to the delivery gate as a path. r97 delivered its milestone and then
failed the final gate on it: "Frontend calls unregistered endpoint(s): GET /api/search${qs ?",
which nobody can register, because it is not a path.

#1202dn already ruled on the consumer side and the ruling stands: reconstructing a truncated
path THERE would be guessing, and a guess that happens to match a registered prefix turns a
false positive into a false NEGATIVE that hides real drift. "The defect belongs to the
extractor." A first attempt at this fix truncated in the consumer anyway and #1202dn's test
caught it — this is the same repair moved to where that test says it belongs.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"))

from multi_agent.delivery.contract_extract import (  # noqa: E402
    extract_frontend_calls, _template_path_1202ge, _path_before_computed_1202ge)


def _calls(src: str):
    d = Path(tempfile.mkdtemp())
    (d / "src").mkdir()
    (d / "src" / "api.js").write_text(src)
    return extract_frontend_calls(d)


def test_a_nested_template_no_longer_truncates_the_path():
    """r97's exact line."""
    calls = _calls("export const s=(qs)=>request(`/api/search${qs ? `?${qs}` : ''}`);")
    assert "GET /api/search" in calls, calls
    assert not [c for c in calls if "${" in c or "`" in c], calls


def test_a_whole_segment_interpolation_stays_a_path_param():
    calls = _calls("export const f=(id)=>request(`/api/users/${id}/follow`,{method:'POST'});")
    assert "POST /api/users/:id/follow" in calls, calls


def test_a_call_expression_param_stays():
    calls = _calls("export const e=(i)=>request(`/api/x/${encodeURIComponent(i)}/y`);")
    assert "GET /api/x/:encodeURIComponent(i)/y" in calls, calls


def test_plain_literals_are_unaffected():
    calls = _calls("const a=()=>request('/api/videos');\n"
                   "const b=(i)=>fetch(`/api/videos/${i}`,{method:'DELETE'});")
    assert "GET /api/videos" in calls and "DELETE /api/videos/:i" in calls, calls


def test_a_computed_suffix_glued_to_a_literal_is_cut_there():
    """`search${qs...}` builds a query; #494 established a query is not a new endpoint."""
    assert _path_before_computed_1202ge("/api/search${qs ? x : y}") == "/api/search"


def test_a_segment_interpolation_is_not_cut():
    raw = "/api/users/${id}/follow"
    assert _path_before_computed_1202ge(raw) == raw


def test_an_unterminated_literal_yields_nothing_rather_than_half():
    assert _template_path_1202ge("`/api/oops", 1, "`") == ""


def test_the_consumer_still_refuses_to_guess():
    """#1202dn's decision must remain in force — this fix does not touch it."""
    from multi_agent.runtime.delivery_gate import _strip_source_fragment_1202dn as strip
    raw = "GET /api/genres/${requireId(id, "
    assert strip(raw) == raw
