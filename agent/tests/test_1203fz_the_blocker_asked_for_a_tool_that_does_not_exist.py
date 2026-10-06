"""#1203fz — the parked-probe blocker demanded an action the lane has no tool for.

`_parked_probe_routes_1202y7` ended with "Delete the handler AND its registry entry". Half of
that is impossible: the lane's hub tool surface carries `registryhub_register_endpoint` and
`registryhub_deprecate_endpoint` and NO delete/unregister tool for an endpoint. And it is also
unnecessary -- the detector reads `served_routes(backend)`, which is CODE, so the handler alone
is what blocks.

r164's backend notebook is the cost, in the lane's own words: "No direct unregister tool is
available", "RegistryHub retains deprecated historical `__` endpoint entries because no delete
tool is available", and -- believing the instruction over the gate -- "the blocking state was
registry contract presence; changed RegistryHub endpoint status to removed".

Measured over every run directory: 14 probes across 8 runs (r121, r125, r123, r164, r114, r120,
netflix-r6, netflix-r24) sit retired in the registry with the handler still in the source, each
one still blocking. 57 across 48 runs deleted the handler and cleared.
"""
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent import hub_tool_surface as hts
from env_generator.llm_generator.multi_agent import tool_bundles as tb
from env_generator.llm_generator.multi_agent.runtime.backend_audit import served_routes
from env_generator.llm_generator.multi_agent.runtime.deliverability import (
    _parked_probe_routes_1202y7)


def _backend(tmp_path, routes, *, include=True):
    """A backend shaped the way `served_routes` really reads one: main.py plus the modules
    it includes. An earlier version of this fixture omitted main.py and the detector returned
    [] on a tree the real r164 backend scores 3 on -- a fixture that disagrees with the corpus
    is testing a world the system does not produce."""
    be = tmp_path / "backend"
    be.mkdir(parents=True, exist_ok=True)
    body = "from fastapi import APIRouter\nrouter = APIRouter()\n"
    for method, path in routes:
        body += '@router.%s("%s")\ndef h_%s():\n    return {}\n' % (
            method, path, abs(hash((method, path))))
    (be / "custom_routes.py").write_text(body, encoding="utf-8")
    main = "from fastapi import FastAPI\napp = FastAPI()\n"
    if include:
        main += ("from custom_routes import router as r\n"
                 "app.include_router(r)\n")
    (be / "main.py").write_text(main, encoding="utf-8")
    return be


def test_the_fixture_matches_what_the_real_reader_sees(tmp_path):
    """Non-vacuity first: the detector must actually see this tree."""
    be = _backend(tmp_path, [("get", "/__noop__"), ("get", "/api/videos")])
    assert ("GET", "/__noop__") in served_routes(be), sorted(served_routes(be))


def test_the_blocker_names_deleting_the_handler(tmp_path):
    _backend(tmp_path, [("get", "/__noop__")])
    out = _parked_probe_routes_1202y7(tmp_path)
    assert len(out) == 1, out
    text = out[0]
    assert "/__noop__" in text
    assert "DELETING THE HANDLER is what clears this check" in text
    assert "reads the routes your backend SERVES, not the registry" in text


def test_the_blocker_says_the_unregister_tool_does_not_exist(tmp_path):
    _backend(tmp_path, [("get", "/__noop__")])
    text = _parked_probe_routes_1202y7(tmp_path)[0]
    assert "no tool that deletes an endpoint registration" in text
    assert "`registryhub_deprecate_endpoint` does NOT clear this" in text
    assert "Leaving the registration behind is fine" in text


def test_it_no_longer_demands_the_registry_entry(tmp_path):
    """The exact sentence that caused the half-repair must be gone."""
    _backend(tmp_path, [("get", "/__noop__")])
    text = _parked_probe_routes_1202y7(tmp_path)[0]
    assert "Delete the handler AND its registry entry" not in text


def _tool_names():
    """Every agent-callable tool name, from the `NAME = "..."` declaration on each tool class.

    THREE narrower universes were tried first and all three were incomplete, each time making a
    real tool look missing:
      * `hub_tool_surface` alone -- misses names declared only in `tool_bundles`;
      * `vars()` of either module -- misses names declared inside a function body, which is
        where `codehub_record_check` lives;
      * `tools.hub_tools.create_hub_tools(HubRegistry(...))` -- returns 77 names and omits
        `registryhub_request_review` and `codehub_review_pr`, both of which ARE tools
        (`RegistryHubRequestReviewTool.NAME`, and its sibling for the PR review).
    The declarations are the surface. 290 of them, and the non-vacuity probes below fail loudly
    if that ever stops being true, because a guard whose universe is smaller than the thing it
    guards reports absences that are its own."""
    import re
    from pathlib import Path as _P
    root = _P(hts.__file__).parents[1] / "tools"
    names = set()
    for py in root.rglob("*.py"):
        names |= set(re.findall(r'^\s*NAME\s*=\s*["\']([A-Za-z_0-9]+)["\']',
                                py.read_text(encoding="utf-8", errors="ignore"), re.M))
    return names


def test_there_really_is_no_endpoint_delete_tool():
    """The blocker's claim is checked against the tool surface, not asserted. If an
    endpoint-deleting tool is ever added, this goes red and #1203fz's wording must change."""
    names = _tool_names()
    for probe in ("registryhub_register_endpoint", "registryhub_deprecate_endpoint",
                  "codehub_record_check", "workhub_task", "registryhub_request_review",
                  "codehub_review_pr", "eventhub_inbox"):
        assert probe in names, (
            "the tool-name universe is incomplete (missing %s); this guard cannot be "
            "trusted" % probe)
    assert len(names) > 200, len(names)
    endpoint_tools = {n for n in names if "endpoint" in n}
    for n in endpoint_tools:
        assert not any(w in n for w in ("delete", "unregister", "remove")), (
            "an endpoint-deleting tool now exists (%s) -- #1203fz's wording is stale" % n)


def test_1203g0_the_prose_no_longer_names_tools_that_do_not_exist():
    """#1203g0 — two names an agent is told to call, that no tool class declares.

    `workhub_create_task` (hub_pulse's reassign nudge and two codehub `hint` payloads) and
    `eventhub_list_inbox` (sync's truncation note). The real ones are
    `workhub_task(action="create", ...)` -- which `approval.py` keys its create-gate on -- and
    `eventhub_inbox`.

    Deliberately NOT a general sweep. The same sweep flagged 18 candidates, of which 12 are
    store filenames and event/error labels and 4 looked like defects until the universe was
    complete: `codehub_review_pr` and `registryhub_request_review` are real tools and the
    "fix" for them was reverted before it landed. A general ratchet would need a 12-entry
    allowlist of things that merely look like tools, and would bless the next typo along with
    them; these two are pinned by name instead."""
    import ast
    import re
    from pathlib import Path as _P
    names = _tool_names()
    gone = ("workhub_create_task", "eventhub_list_inbox")
    for g in gone:
        assert g not in names, "%s is a tool now -- this ratchet is stale" % g
    assert "workhub_task" in names and "eventhub_inbox" in names
    pat = re.compile(r"\b(%s)\b" % "|".join(gone))
    root = _P(hts.__file__).parent
    offenders = []
    for py in root.rglob("*.py"):
        if "__pycache__" in str(py):
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8", errors="ignore"))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for m in pat.finditer(node.value):
                    offenders.append("%s: %s" % (py.name, m.group(1)))
    assert offenders == [], (
        "these strings tell an agent to call a tool that does not exist: %s" % offenders)

def test_the_evidence_still_comes_before_the_prose(tmp_path):
    """#1202vx: the routes are the evidence and must not be pushed out by the explanation.

    Asserted as "the string BEGINS with the count", not as "the names appear before some
    later sentence". The weaker form was written first and a mutation that prepended
    `DELETING THE HANDLER ...` ahead of the count stayed GREEN through it -- which is the exact
    prepend #1202vx measured as letting the prose win. A guard that cannot fail on the thing
    it names is the test, not the code, that needs fixing."""
    be_routes = [("get", "/__noop_%d__" % i) for i in range(9)]
    _backend(tmp_path, be_routes)
    text = _parked_probe_routes_1202y7(tmp_path)[0]
    assert text.startswith("9 served route(s)"), text[:120]
    head = text[:text.index("A path beginning")]
    assert head.count("/__noop_") == 5, head        # join_capped cap=5
    assert "(+4 more not shown)" in head, head     # and the cut is declared (#1034)


def test_a_probe_in_a_module_nobody_includes_does_not_block(tmp_path):
    """`served_routes`: "Orphan, never-included modules are excluded." The gate is about what
    SHIPS, so an unmounted file is correctly silent -- and that is why deleting the handler,
    not the registration, is the instruction."""
    _backend(tmp_path, [("get", "/__noop__")], include=False)
    assert _parked_probe_routes_1202y7(tmp_path) == []


def test_a_clean_backend_is_silent(tmp_path):
    _backend(tmp_path, [("get", "/api/videos"), ("post", "/api/comments")])
    assert _parked_probe_routes_1202y7(tmp_path) == []


def test_the_env_switch_still_disables_it(tmp_path, monkeypatch):
    _backend(tmp_path, [("get", "/__noop__")])
    monkeypatch.setenv("ENVGEN_PARKED_ROUTE_GATE", "0")
    assert _parked_probe_routes_1202y7(tmp_path) == []


def test_the_real_r164_backend_is_the_case_this_describes():
    """The run that paid for it, if its artifacts are still on disk."""
    app = Path(__file__).resolve().parents[2] / "generated" / "tiktok-web-r164" / "app"
    if not (app / "backend" / "main.py").exists():
        pytest.skip("r164 artifacts not on disk")
    out = _parked_probe_routes_1202y7(app)
    assert len(out) == 1
    assert "DELETING THE HANDLER" in out[0]
    assert "/__noop__" in out[0]
