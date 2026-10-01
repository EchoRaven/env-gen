r"""#1203a7: one sentence for three different findings, and for most of them it was false.

`_declared_but_inert` holds whenever a registered page declares `apis_used`, calls no api,
delegates to no child and carries no handler token. The note was always the same: "a
placeholder stub — it renders no real UI/behavior; build the page's declared content".

MEASURED over the corpus's flagged pages (22 after #1203a5):

     17  render real UI — 6+ JSX elements, up to 51 lines — and simply never call the api they
         declared. The sentence is factually wrong for every one of them.
      3  have NO JSX at all. Genuine stubs; the sentence is right.
      1  is a pure `<Navigate to="/foryou">` redirect (r139's RootRedirectPage, 6 lines) whose
         registration declared `GET /api/search` + `GET /api/videos/feed`. A redirect cannot
         call an api, so "build the page's declared content" asks for a page that should not
         exist — the repair belongs in the registration.
      1  renders a token amount of JSX; left with the stub wording.

WHY THE WORDING MATTERS, in this file's own words (#1202y5): "the check asks a page to prove
itself in a currency it does not hold, and gets paid in calls that do not belong there" — r140's
lane cleared seven of these by adding a feed call to a profile page, a notifications page and a
direct-message page alike.

★ NO MASKING: the verdict is untouched. All four cases still append to `missing` and still
block. What changes is which cause is named and which repair is asked for.
"""
import ast
import inspect
import os
import re
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.frontend_audit as FA  # noqa: E402

_SRC = inspect.getsource(FA)


def _verdict_if():
    """The `if _placeholder or _declared_but_inert:` statement, by AST."""
    for node in ast.walk(ast.parse(_SRC)):
        if isinstance(node, ast.If) and "_declared_but_inert" in ast.dump(node.test):
            return node
    raise AssertionError("the inert-page verdict is gone")


def _messages():
    """Every appended message string inside that statement, flattened."""
    out = []
    for n in ast.walk(_verdict_if()):
        if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "append":
            out.append(" ".join(
                c.value for c in ast.walk(n)
                if isinstance(c, ast.Constant) and isinstance(c.value, str)))
    return out


def test_every_branch_still_blocks():
    """★ No masking: each case appends to `missing`, so the verdict is unchanged."""
    msgs = _messages()
    assert len(msgs) >= 3, msgs
    for n in ast.walk(_verdict_if()):
        if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "append":
            assert getattr(n.func.value, "id", "") == "missing", ast.unparse(n)[:120]


def test_the_genuine_stub_wording_survives():
    """3 of the 22 really have no JSX; that case must keep saying so."""
    assert any("placeholder stub" in m and "renders no real" in m for m in _messages())


def test_a_rendering_page_is_not_told_it_renders_nothing():
    """★ The 17. The note must name the real gap — the declared api is never called."""
    m = [x for x in _messages() if "RENDERS UI" in x]
    assert m, _messages()
    assert "never calls the apis_used" in m[0], m[0]
    assert "renders no real" not in m[0], m[0]


def test_the_rendering_note_forbids_the_wrong_repair():
    """#1202y5 measured the wrong repair actually happening: a lane adding a feed call to a
    profile page. The note has to rule it out explicitly."""
    m = [x for x in _messages() if "RENDERS UI" in x][0]
    assert "do NOT add an unrelated api call" in m.replace("Do NOT", "do NOT"), m


def test_a_redirect_is_told_to_fix_its_registration():
    """A `<Navigate>` page cannot call an api; asking it to build content asks for a page that
    should not exist."""
    m = [x for x in _messages() if "REDIRECT" in x]
    assert m, _messages()
    assert "remove apis_used from the registration" in m[0], m[0]
    assert "cannot call an api" in m[0], m[0]


def test_the_branch_order_puts_the_stub_case_first():
    """`_placeholder` (the framework's own marker) and a file with no JSX at all must not be
    reclassified as "renders UI" — the zero-JSX test has to come before the others."""
    node = _verdict_if()
    first = node.body[0]
    assert isinstance(first, ast.Assign) or isinstance(first, ast.If) or True
    # Only the Ifs that actually emit a message — #1034's truncation guard is also an `If`
    # in this body, and keying on "the first If" coupled this test to that detail.
    chain = [n for n in node.body if isinstance(n, ast.If)
             and any(isinstance(c, ast.Call) and getattr(c.func, "attr", "") == "append"
                     for c in ast.walk(n))]
    assert chain, ast.unparse(node)[:300]
    assert "_jsx_n_1203a7 == 0" in ast.unparse(chain[0].test), ast.unparse(chain[0].test)


def test_the_jsx_count_and_redirect_flag_are_computed_from_the_page_text():
    """A branch that reads something nobody fills is the shape this project keeps finding."""
    body = ast.unparse(_verdict_if())
    assert "_jsx_n_1203a7" in body and "comp_file_text" in body
    assert "_redirect_1203a7" in body
    assert "Navigate" in body


def test_the_declared_apis_are_actually_interpolated():
    """The lane has to know WHICH endpoints the registration claims, or "drop the ones this
    page does not own" is not actionable.

    ★ FOUND BY MUTATION. The first version asserted that the word "apis_used" appeared in the
    message — which it does as a literal, so blanking `_apis_1203a7` to "" left every test
    green. A name appearing is not a name being used: pin the FormattedValue, and pin that the
    variable is built from `apis`."""
    import ast as _ast
    import re as _re
    node = _verdict_if()
    interpolated = set()
    for n in _ast.walk(node):
        if isinstance(n, _ast.JoinedStr):
            for part in n.values:
                if isinstance(part, _ast.FormattedValue):
                    interpolated.add(_ast.unparse(part.value))
    assert "_apis_1203a7" in interpolated, (
        "the declared endpoints are never interpolated into any message: %s" % sorted(interpolated))

    # ...and it must be BUILT FROM the registration's list, not from a constant. Checked as
    # a dataflow property over the whole block rather than by slicing one assignment line,
    # which coupled the first version to the exact spelling (#1034 then changed it).
    assigns = {t.id: n.value for n in _ast.walk(node) if isinstance(n, _ast.Assign)
               for t in n.targets if getattr(t, "id", "").endswith("_1203a7")}
    assert "_apis_1203a7" in assigns, sorted(assigns)
    seen, stack, reaches_apis = set(), ["_apis_1203a7"], False
    while stack:
        name = stack.pop()
        if name in seen or name not in assigns:
            continue
        seen.add(name)
        txt = _ast.unparse(assigns[name])
        if _re.search(r"\bapis\b", txt):
            reaches_apis = True
        stack.extend(_re.findall(r"\b\w+_1203a7\b", txt))
    assert reaches_apis, (
        "the quoted endpoints are not derived from `apis`: %s"
        % {k: _ast.unparse(v) for k, v in assigns.items()})

    # both actionable branches must carry it
    for want in ("RENDERS UI", "REDIRECT"):
        msg_node = [n for n in _ast.walk(node) if isinstance(n, _ast.JoinedStr)
                    and want in " ".join(c.value for c in _ast.walk(n)
                                         if isinstance(c, _ast.Constant)
                                         and isinstance(c.value, str))]
        assert msg_node, want
        used = {_ast.unparse(p.value) for p in msg_node[0].values
                if isinstance(p, _ast.FormattedValue)}
        assert "_apis_1203a7" in used, "%s branch does not quote the endpoints: %s" % (want, used)


def test_the_three_classifications_are_live_on_the_real_pages():
    """Against the artifacts the measurement came from, when they are on this machine."""
    import glob
    import json
    root = os.path.dirname(_AGENT)
    seen = set()
    jsx = re.compile(r"<[A-Za-z][\w.]*[\s/>]")
    for run, comp, expect in (("tiktok-web-r139", "RootRedirectPage", "redirect"),
                              ("netflix-local-r26", "GamesPage", "renders"),
                              ("tiktok-web-r90", "LoginPage", "stub")):
        hits = glob.glob(os.path.join(root, "generated", run, "app", "frontend", "src",
                                      "**", comp + ".jsx"), recursive=True)
        hits = [h for h in hits if "/worktrees/" not in h]
        if not hits:
            continue
        with open(hits[0], encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        n = len(jsx.findall(text))
        got = ("stub" if n == 0 else
               "redirect" if re.search(r"<Navigate\b", text) else "renders")
        assert got == expect, "%s/%s: %d jsx -> %s, expected %s" % (run, comp, n, got, expect)
        seen.add(expect)
    if not seen:
        import pytest
        pytest.skip("none of the sample runs are on this machine")
