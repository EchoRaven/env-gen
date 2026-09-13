"""#1202lt — the gate told the lane to register a JavaScript expression as a contract path.

GROUND TRUTH (tiktok-web-r121, from its own delivery_gate.jsonl, verbatim):

    Frontend calls unregistered endpoint(s) (register in RegistryHub):
      GET /api/sounds, GET /api/videos,
      GET /api/videos/:encodeURIComponent(id),
      GET /api/videos/:encodeURIComponent(id)/comments,
      GET /auth/logout

`:encodeURIComponent(id)` is a JS template literal the frontend extractor flattened, not a
path parameter. The lane did what the message said — the registry still carries

    GET /api/videos/{encodeURIComponent}(id)          status=deprecated
    GET /api/videos/{encodeURIComponent}(id)/comments status=deprecated

— then deprecated them once it saw what they were, and those retired registrations went on to
manufacture required tasks in the run's final minutes (#1202lr). The framework asked a lane to
chase a defect that did not exist, which is the one thing framework-authored instructions are
not allowed to do.

The MATCHING side was already param-agnostic (#494). Only the message was raw.
"""
import inspect
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg


def _render():
    """The nested helper, lifted out of validate_contract_alignment by exec."""
    src = inspect.getsource(dg.validate_contract_alignment)
    lines = src.splitlines()
    start = next(i for i, l in enumerate(lines)
                 if "def _registerable_path_1202lt" in l)
    indent = len(lines[start]) - len(lines[start].lstrip())
    body = [lines[start][indent:]]
    for l in lines[start + 1:]:
        if l.strip() and (len(l) - len(l.lstrip())) <= indent:
            break
        body.append(l[indent:] if l.strip() else "")
    ns = {"re": re}
    exec("\n".join(body), ns)
    return ns["_registerable_path_1202lt"]


@pytest.mark.parametrize("raw,want", [
    # ★ r121's own two, verbatim from the ledger
    ("GET /api/videos/:encodeURIComponent(id)", "GET /api/videos/{id}"),
    ("GET /api/videos/:encodeURIComponent(id)/comments", "GET /api/videos/{id}/comments"),
    # other shapes the extractor produces
    ("GET /api/videos/${videoId}", "GET /api/videos/{videoId}"),
    ("GET /api/users/:userId/posts", "GET /api/users/{userId}/posts"),
    ("GET /api/videos/${encodeURIComponent(video.id)}", "GET /api/videos/{id}"),
    # already-clean paths must come through untouched
    ("GET /api/sounds", "GET /api/sounds"),
    ("GET /auth/logout", "GET /auth/logout"),
    ("GET /api/videos/{id}", "GET /api/videos/{id}"),
    # a query string is not an endpoint (#494's rule, kept)
    ("GET /api/titles?kind=movie", "GET /api/titles"),
])
def test_a_scraped_call_renders_as_something_registerable(raw, want):
    assert _render()(raw) == want


def test_nothing_registerable_still_yields_a_real_param():
    r = _render()
    assert r("GET /api/videos/${}") == "GET /api/videos/{id}"
    assert r("GET /api/videos/:") == "GET /api/videos/{id}"


def test_it_never_raises_on_junk():
    r = _render()
    for junk in ("", None, "   ", "GET", "///"):
        r(junk)          # must not raise


def test_the_message_names_the_registerable_path():
    # Located structurally: the string also appears in the fix's own docstring above, so
    # `src.index(...)` finds the explanation rather than the statement (it did, first try).
    import ast
    src = inspect.getsource(dg.validate_contract_alignment)
    tree = ast.parse(src.lstrip() if src.startswith(" ") else src)
    appends = [ast.unparse(n) for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "append"
               and "Frontend calls unregistered endpoint" in (ast.unparse(n) or "")]
    assert appends, "the unregistered-call error moved"
    stmt = appends[0]
    assert "_shown_1202lt" in stmt, (
        "the error still reports the raw scrape — the lane registers what the message says")
    assert "unregistered_calls" not in stmt, (
        "the raw list must not be what gets joined into the message")


def test_the_raw_scrape_is_kept_beside_it():
    """The lane still needs to find the source line; only the ones that differ carry it."""
    src = inspect.getsource(dg.validate_contract_alignment)
    assert "source spells it" in src
    assert "_reg if _reg == _c else" in src, (
        "a clean path must read exactly as it did before — no parenthetical noise")
