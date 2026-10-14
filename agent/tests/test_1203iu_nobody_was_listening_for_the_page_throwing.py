r"""#1203iu: the auth-flow probe never listened for the page throwing.

`_ui_auth_flow` attaches response, request and requestfailed — and nothing else. A submit
handler that raises fires no request, stores no token and navigates nowhere, which the note
ladder reads as "submit sent NO /auth request — the form is not wired to the API (button has
no handler / submit does nothing)". The JS error that actually stopped it was never recorded,
so none of those verdicts could be checked afterwards.

This is #1203a6's argument one step further. Its words, about this same ladder: "NONE of the
378 can be audited, because the record kept neither the URL nor whether a request was even
attempted. Playwright hands both facts over; nothing was asking for them." It hands the page
errors over too.

The guess is NOT deleted — removing it would be another guess. It is simply not reached when
the page itself said what went wrong. (Counted against their own frontends, 71 of the 73 runs
that produced it have both a submit handler and an auth call on an auth page, and 172 of 173
runs have a handler at all; that is recorded, and rewording the branch touches assertions in
three other tickets, so it is not done here.)

The reading is `page_error_fields_1202br`, lifted out of `BrowserManager._on_page_error`
rather than written a third time (#1032). `test_the_real_playwright_error_has_the_fields_it
_reads` drives a real Chromium, because the whole point of #1202br is that the obvious
reading — `str(error)` — yields a minified bundle location a lane cannot open.
"""
import ast
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import test_user_validation as tuv
from env_generator.llm_generator.tools.browser import _manager as mgr

VSRC = inspect.getsource(tuv)
MSRC = inspect.getsource(mgr)


def _flow():
    for n in ast.walk(ast.parse(VSRC)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_ui_auth_flow":
            return n
    raise AssertionError("_ui_auth_flow is gone")


def _route_loop():
    for n in ast.walk(_flow()):
        if isinstance(n, (ast.For, ast.AsyncFor)):
            consts = {c.value for c in ast.walk(n.iter)
                      if isinstance(c, ast.Constant) and isinstance(c.value, str)}
            if "/signup" in consts and "/login" in consts:
                return n
    raise AssertionError("the signup+login loop is gone")


# --- the real object, which is what #1202br is about ------------------------------------------

def test_the_real_playwright_error_has_the_fields_it_reads():
    """`.message` on a REAL pageerror, not a stand-in with the attributes I hoped for.

    Skips only when Playwright or its browser is absent; when it can run, a reading that
    stopped working against the real object turns this red.
    """
    import asyncio
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:                                     # pragma: no cover
        pytest.skip("playwright not installed: %s" % exc)

    page_html = """<html><body><form id="f"><input name="email"><button type="submit">Go
      </button></form><script>
      document.getElementById('f').addEventListener('submit', function (e) {
        e.preventDefault();
        window.__nope.handleSubmit();   // the shape this ticket exists for
      });
      </script></body></html>"""

    async def _run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(args=["--no-sandbox"])
            try:
                page = await (await browser.new_context()).new_page()
                caught = []
                page.on("pageerror", lambda e: caught.append(
                    mgr.page_error_fields_1202br(e)))
                await page.set_content(page_html)
                await page.click("button[type=submit]")
                await page.wait_for_timeout(300)
                return caught
            finally:
                await browser.close()

    try:
        caught = asyncio.run(_run())
    except Exception as exc:                                     # pragma: no cover
        pytest.skip("no usable browser: %s" % str(exc)[:120])

    assert caught, "a submit handler threw and no pageerror arrived"
    got = caught[0]
    assert got["message"], "the real error carried no .message — #1202br's reading is stale"
    assert "__nope" in got["message"] or "undefined" in got["message"].lower(), got["message"]
    # the scar: a bare str(error) is a bundle location, which is why .message is read
    assert got["message"] not in ("", None)
    assert len(got["text"]) <= 4000


def test_a_page_that_does_not_throw_produces_nothing():
    """Non-vacuity in the other direction: the listener must not invent an error."""
    import asyncio
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:                                     # pragma: no cover
        pytest.skip("playwright not installed: %s" % exc)

    async def _run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(args=["--no-sandbox"])
            try:
                page = await (await browser.new_context()).new_page()
                caught = []
                page.on("pageerror", lambda e: caught.append(e))
                await page.set_content("<html><body><p>fine</p></body></html>")
                await page.wait_for_timeout(200)
                return caught
            finally:
                await browser.close()

    try:
        assert asyncio.run(_run()) == []
    except AssertionError:
        raise
    except Exception as exc:                                     # pragma: no cover
        pytest.skip("no usable browser: %s" % str(exc)[:120])


# --- one owner ---------------------------------------------------------------------------------

def test_the_manager_reads_through_the_shared_function():
    """Behaviour-preserving: the method keeps its record, not its own reading (#1032)."""
    tree = ast.parse(MSRC)
    method = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_on_page_error")
    calls = {ast.unparse(c.func) for c in ast.walk(method) if isinstance(c, ast.Call)}
    assert "page_error_fields_1202br" in calls, sorted(calls)


def test_the_managers_record_shape_is_unchanged():
    """The console_logs entry other readers consume must keep every key."""
    tree = ast.parse(MSRC)
    method = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_on_page_error")
    keys = set()
    for node in ast.walk(method):
        if isinstance(node, ast.Dict):
            keys |= {k.value for k in node.keys
                     if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    assert {"type", "text", "message", "error_name", "stack", "location"} <= keys, sorted(keys)


def test_the_probe_does_not_read_the_error_itself():
    """A second copy of the .message/.name/.stack reading is the drift #1032 names.

    The property is about the ERROR OBJECT, not about the word: reading `_f.get("message")`
    off the shared function's result is the whole point. A first version of this test banned
    the string and failed on exactly that line — the predicate was wider than the rule.
    """
    flow = _flow()
    bad = {"message", "stack"}
    for node in ast.walk(flow):
        if isinstance(node, ast.Attribute) and node.attr in bad:
            raise AssertionError("reads .%s off an object: %s"
                                 % (node.attr, ast.unparse(node)))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "getattr" and len(node.args) > 1
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in (bad | {"name"})):
            raise AssertionError("getattr for %r — that reading has one owner"
                                 % node.args[1].value)


def test_the_shared_function_is_defined_once():
    assert MSRC.count("def page_error_fields_1202br") == 1


# --- the probe's wiring ------------------------------------------------------------------------

def test_the_probe_now_listens_for_pageerror():
    body = ast.unparse(_flow())
    assert '"pageerror"' in body or "'pageerror'" in body


def test_the_listener_is_attached_beside_the_other_three():
    """All four come from one place, so one cannot be forgotten on a refactor."""
    body = ast.unparse(_flow())
    for event in ("response", "request", "requestfailed", "pageerror"):
        assert ("page.on('%s'" % event) in body or ('page.on("%s"' % event) in body, event


def test_the_error_list_is_bound_inside_the_route_loop():
    """The loop never detaches its listeners, so by /login the /signup handlers are still
    live; they close over the /signup list, which nothing reads again. A hoisted list would
    report the signup flow's errors against the login flow."""
    loop = _route_loop()
    assigned = [n for n in ast.walk(loop) if isinstance(n, ast.Assign)
                or isinstance(n, ast.AnnAssign)]
    names = set()
    for node in assigned:
        tgts = node.targets if isinstance(node, ast.Assign) else [node.target]
        names |= {t.id for t in tgts if isinstance(t, ast.Name)}
    assert "_page_errors_1203iu" in names, sorted(n for n in names if "page" in n)


def test_the_record_keeps_the_errors_whether_or_not_the_note_used_them():
    """#1203a6's rule: persist the grounds, not only the verdict."""
    body = ast.unparse(_flow())
    assert "'page_errors'" in body or '"page_errors"' in body


# --- evidence before the guess, and the guess still there --------------------------------------

def test_the_error_branch_is_reached_before_the_unwired_guess():
    """Textual order is not enough: a mutation that made the condition `False and ...` left
    the branch first in the source and dead at runtime, and survived the first version of
    this test. The condition itself is what is asserted now."""
    found = None
    for node in ast.walk(_flow()):
        if not isinstance(node, ast.If):
            continue
        names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
        if "_page_errors_1203iu" not in names:
            continue
        src = ast.unparse(node.test)
        assert "_auth_resps" in names, src          # it must still be the no-response case
        assert not any(isinstance(c, ast.Constant) and c.value in (False, 0)
                       for c in ast.walk(node.test)), "the branch is switched off: %s" % src
        assert "_page_errors_1203iu[0]" in ast.unparse(node.body), src
        found = node
        break
    assert found is not None, "no branch decides on the captured page errors"
    body = ast.unparse(_flow())
    assert body.index("_page_errors_1203iu[0]") < body.index("not wired to the API")


def test_the_error_branch_fires_only_when_the_page_threw():
    """#1203a6's technique rather than mine. My own reachability check banned a constant
    `False` in the condition, which catches `False and …` and nothing else; evaluating the
    condition on both cases is what actually pins the behaviour, and that file says so in
    as many words ("Position is not reachability").
    """
    cond = None
    for node in ast.walk(_flow()):
        if (isinstance(node, ast.If)
                and "_page_errors_1203iu" in {n.id for n in ast.walk(node.test)
                                              if isinstance(n, ast.Name)}):
            cond = ast.unparse(node.test)
            break
    assert cond, "no branch decides on the captured page errors"
    base = {"_auth_resps": [], "_auth_reqs": [], "_auth_failed": [], "ok": False,
            "_page_errors_1203iu": []}
    assert bool(eval(cond, {}, base)) is False, "it fires with nothing thrown: %s" % cond
    thrown = dict(base, _page_errors_1203iu=["TypeError: handleSubmit is not a function"])
    assert bool(eval(cond, {}, thrown)) is True, "it does not fire on its own case: %s" % cond
    # and it must still be the no-response case, not any failure
    answered = dict(thrown, _auth_resps=[401])
    assert bool(eval(cond, {}, answered)) is False, cond


def test_the_unwired_claim_is_still_locatable():
    """Demoted by evidence, not removed on another guess: #612's, #1203a6's, #1203b6's and
    #1203g1's tests all locate that branch by this phrase.

    A first version of this also asserted "button has no handler", the mechanism the branch
    used to name. #1203iw measured that mechanism (71 of 73 of the runs emitting the note
    have a handler) and demoted it, and this assertion then passed only because MY OWN
    COMMENT above still quoted the words — a test reading its author's prose rather than the
    code, which is the trap this session kept finding. The phrase that other tickets depend
    on is what is asserted; the mechanism is #1203iw's business and its own test's.
    """
    assert "the form is not wired to the API" in VSRC


def test_the_note_names_the_error_it_found():
    body = ast.unparse(_flow())
    assert "the page threw first" in body


# --- the sibling probe, which had the same gap -------------------------------------------------

def _runner_src():
    from env_generator.llm_generator.multi_agent.runtime import test_user_runner as tur
    return inspect.getsource(tur)


def test_the_sibling_walk_also_listens_now():
    """`page.on("console", ...)` keeps `m.type == "error"`, which an uncaught throw does not
    produce. Fixing one of two readers is worse than fixing neither — three rules differed
    between these two modules today (#1203ip, #1203it, this)."""
    src = _runner_src()
    assert 'page.on("pageerror"' in src or "page.on('pageerror'" in src


def test_the_sibling_uses_the_same_reading():
    src = _runner_src()
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
               and n.name == "_page_error_entry_1203iu"), None)
    assert fn is not None, "the sibling formats its page errors somewhere else"
    calls = {ast.unparse(c.func) for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "page_error_fields_1202br" in calls, sorted(calls)


def test_the_sibling_entry_is_marked_with_its_source():
    """It shares the console list, as `_manager` does with its own page errors, so the entry
    has to say which stream it came from.

    Asserted by CALLING it. A first version matched the prefix in the module source and a
    mutation that dropped it from the happy path survived — the `except` fallback still spells
    it, so the text was there while the output was not.
    """
    from env_generator.llm_generator.multi_agent.runtime import test_user_runner as tur

    class _Err(Exception):
        message = "TypeError: handleSubmit is not a function"
        name = "TypeError"
        stack = "TypeError: x\n at a"

    out = tur._page_error_entry_1203iu(_Err())
    assert out.startswith("[page error] "), out
    assert "handleSubmit" in out, out
    assert len(out) <= 400, len(out)


def test_the_sibling_entry_survives_an_unreadable_error():
    """A formatter that raises would lose the error entirely — #1202br's own rule."""
    from env_generator.llm_generator.multi_agent.runtime import test_user_runner as tur

    class _Hostile:
        def __getattr__(self, name):
            raise RuntimeError("no")

        def __str__(self):
            raise RuntimeError("no")

    out = tur._page_error_entry_1203iu(_Hostile())
    assert out.startswith("[page error] "), out


def test_the_sibling_does_not_read_the_error_itself():
    tree = ast.parse(_runner_src())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "_page_error_entry_1203iu")
    for node in ast.walk(fn):
        assert not (isinstance(node, ast.Attribute) and node.attr in ("message", "stack")), \
            ast.unparse(node)


def test_both_probes_now_cover_the_same_event_set():
    """The drift guard: whatever one listens for about errors, so does the other."""
    vs, rs = VSRC, _runner_src()
    for event in ("pageerror",):
        assert ('page.on("%s"' % event) in vs, event
        assert ('page.on("%s"' % event) in rs, event


# --- provenance -------------------------------------------------------------------------------

def test_the_reason_the_listener_was_missing_is_recorded():
    flat = " ".join(VSRC.replace("#", " ").split())
    assert "NOBODY WAS LISTENING FOR THE PAGE THROWING" in flat
    assert "Playwright hands the page errors over too" in flat


def test_the_scar_it_reuses_is_recorded_where_it_moved():
    flat = " ".join(MSRC.replace("#", " ").split())
    assert "netflix-r33" in flat
    assert "minified" in flat


def test_why_the_list_must_stay_in_the_loop_is_recorded():
    flat = " ".join(VSRC.replace("#", " ").split())
    assert "never detaches them" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
