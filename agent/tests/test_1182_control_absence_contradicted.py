"""#1182 — "the control is not there", said about a control that is there and works.

Twice a run has ended on a walk that could not FIND a control, on a page whose source
declares it and whose flow works when driven by hand:

  r17  ui_flow:signup           "input[name='email'] was not present/interactable"
       -> the form was complete; the inputs carried no `name` (fixed at source by #1179b).
  r19  ui_flow:search_discovery "no interactable search/text input exists"
       -> SearchPage.jsx declares
            <input type="search" name="q" placeholder="..." autoFocus aria-label="Search"/>
          A probe written as `input[type=text]` does not match `type="search"`. r19 aborted
          STUCK on that one record after 18 coordination ticks, at $355.

The framework has the page source, so it can answer without judgement: resolve the route the
record names to the component App.jsx renders there, read the file, and put the declared
controls in the remediation with the attributes needed to select them.

It never contradicts a real defect -- it speaks only when the file genuinely declares a
control, and it prescribes RE-LOCATING, never closing the item.
"""
import json

from env_generator.llm_generator.multi_agent.runtime.remediation_dispatcher import (
    control_absence_contradicted_1182, _control_tags_1182, _page_controls_1182,
)


class _Orch:
    def __init__(self, root):
        self.output_dir = str(root)


_SEARCH_PAGE = (
    'export default function SearchPage() {\n'
    '  return <form><input className="field" type="search" name="q" value={query}\n'
    '     onChange={(e)=>setQuery(e.target.value)} placeholder="Search titles"\n'
    '     autoFocus aria-label="Search"/></form>;\n}\n'
)
# r19's guard is <Authed> -- a name no hardcoded guard vocabulary contained.
_APP = ('<Routes>\n'
        '  <Route path="/search" element={<Authed><SearchPage /></Authed>} />\n'
        '  <Route path="/browse" element={<Authed><BrowseHomePage /></Authed>} />\n'
        '</Routes>')


def _project(tmp_path, summary, pages=(("SearchPage", _SEARCH_PAGE),)):
    hubs = tmp_path / "shared" / "hubs"
    hubs.mkdir(parents=True)
    (hubs / "codehub_checks.json").write_text(json.dumps({"checks": [{
        "name": "validation:ui_flow:search_discovery", "status": "failure",
        "evidence": {"summary": summary}}]}))
    src = tmp_path / "app" / "frontend" / "src" / "pages"
    src.mkdir(parents=True)
    (src.parent / "App.jsx").write_text(_APP)
    for name, body in pages:
        (src / f"{name}.jsx").write_text(body)
    return _Orch(tmp_path)


def test_the_declared_control_answers_the_record(tmp_path):
    orch = _project(tmp_path, "FAIL: authenticated /search page loaded but no interactable "
                              "search/text input exists, so the flow cannot be exercised.")
    out = control_absence_contradicted_1182(orch, ["search_discovery"])
    assert out, "the contradiction that ended r19 must be stated"
    assert 'type="search"' in out and 'name="q"' in out
    assert 'aria-label="Search"' in out, "the best selector must survive extraction"
    assert "SELECTOR, not the app" in out
    # It must prescribe re-locating, never closing the item.
    assert "getByRole" in out and "record stays red" in out


def test_a_page_with_no_control_says_nothing(tmp_path):
    orch = _project(tmp_path, "/search page loaded but no interactable input exists",
                    pages=(("SearchPage", "export default function SearchPage(){return <div/>;}"),))
    assert control_absence_contradicted_1182(orch, ["search_discovery"]) == ""


def test_a_failure_that_is_not_about_absence_says_nothing(tmp_path):
    orch = _project(tmp_path, "/search returned 500 from GET /api/search")
    assert control_absence_contradicted_1182(orch, ["search_discovery"]) == ""


def test_an_app_state_message_is_not_mistaken_for_a_missing_control(tmp_path):
    """'No results match your search' is a STATE, not an absent control."""
    orch = _project(tmp_path, "/search showed 'No results match your search' after typing")
    assert control_absence_contradicted_1182(orch, ["search_discovery"]) == ""


def test_a_jsx_handler_does_not_truncate_the_tag():
    """★ Plant the defect: `[^>]*` stops at the `>` inside `(e)=>setQuery(...)`, losing
    placeholder and aria-label — exactly the attributes worth reporting."""
    tags = _control_tags_1182(_SEARCH_PAGE)
    assert len(tags) == 1
    assert "aria-label" in tags[0] and "placeholder" in tags[0]
    import re
    naive = re.findall(r"<input\b[^>]*", _SEARCH_PAGE)
    assert "aria-label" not in naive[0], "the naive scan must still show the truncation"


def test_the_page_is_found_past_a_guard_it_does_not_know(tmp_path):
    """Resolution picks the component that HAS a page file, not one off a guard word list."""
    orch = _project(tmp_path, "x")
    comp, ctrls = _page_controls_1182(orch.output_dir, "/search")
    assert comp == "SearchPage" and ctrls, "must see past <Authed>"
    assert _page_controls_1182(orch.output_dir, "/nope") == (None, [])
