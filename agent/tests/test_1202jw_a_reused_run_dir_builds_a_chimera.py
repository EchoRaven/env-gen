"""#1202jw: a reused output dir keeps the previous environment's reference screens.

Staging is additive — `stage_reference_docs` and the image staging both copy into
`<run>/design/references/` and neither clears it — so a run started into a directory another
environment already used builds its contract from the UNION of both screen sets.

googlemaps-r16 is the case, and the only one in 148 runs. Its `design/references/` holds
netflix's 20 `.jpg` screens (staged 13:47) beside google_maps' 29 `.png` (18:58), down to
`account_menu` in both spellings; its registered tables are `continue_watching`, `episodes`,
`genres`, `my_list`, `profiles` next to `places`, `directions`, `routes`; and its own
validation says it plainly — "required Netflix UI routes are serving the Google Maps shell".
The run built a chimera, spent its budget, and every number it produced is unusable. It
polluted this session's own corpus measurements before I recognised it.

DETECTS, never deletes. One occurrence in 148 says the frequency is low and the cost is total,
which is the shape a cheap loud check fits — and a framework that removes files it did not
write is a worse failure than the one it prevents.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

import ast                                                             # noqa: E402
import inspect                                                         # noqa: E402

from env_generator.llm_generator.multi_agent.runtime import design_prep as DP  # noqa: E402


def _staged(tmp, *names):
    d = tmp / "design" / "references"
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        (d / n).write_bytes(b"x")
    return d


def test_a_previous_environments_screens_are_named(tmp_path):
    """★ googlemaps-r16's shape, in miniature."""
    _staged(tmp_path, "home_map.png", "atm_search_results.png",
            "browse_home.jpg", "account_menu.jpg")
    resolved = {"references": ["/in/google_maps/references/home_map.png",
                               "/in/google_maps/references/atm_search_results.png"],
                "docs": []}
    assert DP.foreign_references_1202jw(tmp_path, resolved) == [
        "account_menu.jpg", "browse_home.jpg"]


def test_a_clean_run_reports_nothing(tmp_path):
    _staged(tmp_path, "home_map.png")
    assert DP.foreign_references_1202jw(
        tmp_path, {"references": ["/in/home_map.png"], "docs": []}) == []


def test_staged_documents_count_as_declared(tmp_path):
    """`stage_reference_docs` copies docs into the same directory — they are not strangers."""
    _staged(tmp_path, "home_map.png", "features.md")
    resolved = {"references": ["/in/home_map.png"], "docs": ["/in/features.md"]}
    assert DP.foreign_references_1202jw(tmp_path, resolved) == []


def test_an_empty_input_accuses_nobody(tmp_path):
    """#1039's invariant: nothing declared cannot mean everything is foreign."""
    _staged(tmp_path, "home_map.png", "browse_home.jpg")
    assert DP.foreign_references_1202jw(tmp_path, {"references": [], "docs": []}) == []


def test_a_missing_directory_is_not_an_error(tmp_path):
    assert DP.foreign_references_1202jw(tmp_path, {"references": ["/in/a.png"]}) == []


def test_it_never_deletes(tmp_path):
    d = _staged(tmp_path, "home_map.png", "browse_home.jpg")
    DP.foreign_references_1202jw(tmp_path, {"references": ["/in/home_map.png"]})
    assert {p.name for p in d.iterdir()} == {"home_map.png", "browse_home.jpg"}
    # Read the CODE, not the prose: the first version matched the word "removes" in this
    # function's own docstring, which is #923's bare-text lesson one file over.
    body = ast.parse(inspect.getsource(DP.foreign_references_1202jw))
    called = {getattr(n.func, "attr", None) or getattr(n.func, "id", None)
              for n in ast.walk(body) if isinstance(n, ast.Call)}
    for verb in ("unlink", "rmtree", "remove", "rename", "replace", "write_bytes",
                 "write_text"):
        assert verb not in called, f"this check must not {verb}() — it reports, never repairs"


def test_it_is_wired_before_the_phase_it_warns_about():
    """★ Reachability: warning after design-prep has run costs the whole run anyway."""
    from env_generator.llm_generator.multi_agent import orchestrator as ORCH
    src = inspect.getsource(ORCH)
    i = src.index("foreign_references_1202jw(self.output_dir, resolved)")
    j = src.index("write_skeleton_design_system(resolved, self.output_dir)")
    assert i < j, "the check must precede the design-prep work it exists to invalidate"
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "foreign_references_1202jw"]
    assert len(calls) == 1
