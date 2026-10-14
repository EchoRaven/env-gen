r"""#1203ip: the probe typed `uiflow7` into a birthdate field and blamed the app.

`#670` opened `test_user_reports/` and split visible inputs in two: the types `fill()`
REFUSES (skip them) and everything else (fill with text). A third category was left in the
second half — the types `fill()` ACCEPTS and then validates the VALUE of:

    r185  Error: Locator.fill: Error: Malformed value
          — waiting for locator("input").nth(2|3|4)
            — locator resolved to <input value="" type="date" name="birthdate"

Measured over the 361 test-user reports on this machine: 270 ui_flows fail, and 11 of them
across 6 runs (r92, r140, r164, r178, r184, r185) are this error. EVERY one is `flow=signup`
and EVERY one resolved to `input[type=date]`. r185's signup form is
name / username / email / password / birthdate, so `nth(4)` is the birthdate — the throw
escaped the per-input guard, aborted the whole flow, and the run reported a UI signup
failure. The app was fine.

Two emitters fill a form by heuristics, and #670 only ever reached one of them:
`test_user_validation._fill_visible_inputs` (no per-input guard → the flow ABORTS) and
`test_user_runner._fill_visible_inputs` (per-input `except` → the throw is swallowed, and so
is the FILL: the field stays empty and `filled` is not counted). This ticket gives both one
owner for both rules (#1032).

The six values are not reasoned from the HTML grammar — `test_a_real_browser_rejects_the_old
_value_and_accepts_the_new_one` drives a real Chromium and asserts both halves.
"""
import ast
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import test_user_runner as tur
from env_generator.llm_generator.multi_agent.runtime import test_user_validation as tuv

TYPED = tuv._TYPED_INPUT_VALUES_1203ip
SKIP = tuv._UNFILLABLE_INPUT_TYPES_670


# --- the type the corpus actually caught -------------------------------------------------------

def test_date_is_covered():
    """Every one of the 11 observed failures was `input[type=date]`."""
    assert "date" in TYPED


def test_date_gets_an_iso_date_and_not_a_generic_string():
    from datetime import date
    assert date.fromisoformat(TYPED["date"])


def test_the_date_is_old_enough_for_an_age_gate():
    """A signup form that asks for a birthdate may also enforce a minimum age."""
    from datetime import date
    assert (date.today() - date.fromisoformat(TYPED["date"])).days > 25 * 365


# --- the set ----------------------------------------------------------------------------------

@pytest.mark.parametrize("typ", ["date", "datetime-local", "month", "week", "time", "number"])
def test_every_value_validating_type_is_covered(typ):
    assert typ in TYPED


def test_it_contains_no_product_literals():
    """Standard HTML input types only — same discipline #670 holds itself to."""
    html = {"button", "checkbox", "color", "date", "datetime-local", "email", "file", "hidden",
            "image", "month", "number", "password", "radio", "range", "reset", "search",
            "submit", "tel", "text", "time", "url", "week"}
    assert set(TYPED) <= html


def test_a_type_is_never_both_skipped_and_filled():
    """The two rules must not disagree about one type."""
    assert not (set(TYPED) & SKIP)


def test_number_is_filled_rather_than_skipped():
    """#670 asserts `number` is NOT skipped because skipping hides a wiring failure.
    So it has to be FILLED — with a number."""
    assert "number" not in SKIP and "number" in TYPED
    assert TYPED["number"].strip().isdigit()


def test_the_free_text_types_are_left_to_the_placeholder_chain():
    """`text`/`email`/`password`/`tel`/`search`/`url` accept any string; claiming them here
    would override the placeholder reading that picks the RIGHT credential."""
    for typ in ("text", "email", "password", "tel", "search", "url", ""):
        assert typ not in TYPED


# --- the real browser: the bug exists, and the fix holds ---------------------------------------

def test_a_real_browser_rejects_the_old_value_and_accepts_the_new_one():
    """The authority on what `fill()` accepts is `fill()`.

    Skips only when Playwright or its browser is absent; when it can run, a regression in
    any of the six values turns it red.
    """
    import asyncio
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:                                  # pragma: no cover
        pytest.skip("playwright not installed: %s" % exc)

    form = "<html><body><form>%s</form></body></html>" % "".join(
        '<input type="%s">' % t for t in TYPED)

    async def _run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(args=["--no-sandbox"])
            try:
                page = await (await browser.new_context()).new_page()
                await page.set_content(form)
                out = []
                for i, (typ, value) in enumerate(TYPED.items()):
                    loc = page.locator("input").nth(i)
                    try:
                        await loc.fill("uiflow7")             # what the `else` branch sends
                        old_threw = False
                    except Exception:
                        old_threw = True
                    try:
                        await loc.fill(value)
                        new_ok = True
                    except Exception:
                        new_ok = False
                    out.append((typ, old_threw, new_ok))
                return out
            finally:
                await browser.close()

    try:
        results = asyncio.run(_run())
    except Exception as exc:                                  # pragma: no cover
        pytest.skip("no usable browser: %s" % str(exc)[:120])

    assert results, "the probe produced no rows"
    for typ, old_threw, new_ok in results:
        assert old_threw, "%s: the generic text was accepted, so this type does not belong" % typ
        assert new_ok, "%s: fill() rejected %r" % (typ, TYPED[typ])


# --- wiring: test_user_validation --------------------------------------------------------------

def _validation_fill_block():
    """The fill loop, bounded by the construct that follows it (#943: no byte windows)."""
    src = inspect.getsource(tuv)
    i = src.index("async def _fill_visible_inputs")
    return src[i:src.index("# Up to 3 fill+submit rounds", i)]


def test_the_typed_branch_is_reached_before_any_placeholder_is_read():
    """r185's field is `placeholder="Birthdate" type="date"`; the placeholder chain matches
    none of its words, so the field fell through to the generic text `else`."""
    body = _validation_fill_block()
    assert "if typ in _TYPED_INPUT_VALUES_1203ip:" in body
    assert body.index("_TYPED_INPUT_VALUES_1203ip") < body.index('"email" in ph')


def test_the_unfillable_skip_still_comes_first():
    """A `color` input is in BOTH halves' reach; #670's skip must keep winning."""
    body = _validation_fill_block()
    assert body.index("_UNFILLABLE_INPUT_TYPES_670") < body.index("_TYPED_INPUT_VALUES_1203ip")


def test_the_catch_all_else_survives():
    """#1203ip narrows what reaches the else; removing the else would strand plain inputs."""
    assert "else:" in _validation_fill_block()


def test_the_typed_branch_fills_from_the_map_and_not_a_literal():
    """A second copy of the value would drift from the map (#1032)."""
    body = _validation_fill_block()
    i = body.index("if typ in _TYPED_INPUT_VALUES_1203ip:")
    nxt = body[i:].splitlines()[1]
    assert "_TYPED_INPUT_VALUES_1203ip[typ]" in nxt, nxt


# --- wiring: test_user_runner, the second emitter ----------------------------------------------

def _runner_fill_fn():
    src = inspect.getsource(tur)
    i = src.index("async def _fill_visible_inputs")
    return src[i:src.index("\nasync def ", i + 10)] if "\nasync def " in src[i + 10:] else src[i:]


def test_both_emitters_read_the_same_two_objects():
    """Not equal values — the same objects, so neither can drift (#1032)."""
    assert tur._UNFILLABLE_INPUT_TYPES_670 is tuv._UNFILLABLE_INPUT_TYPES_670
    assert tur._TYPED_INPUT_VALUES_1203ip is tuv._TYPED_INPUT_VALUES_1203ip


def test_the_runner_no_longer_states_the_unfillable_rule_itself():
    """Its own literal set omitted reset/image/file/range/color — a strict subset of #670's,
    which is how one rule with two copies drifts. Nothing in this module may re-state it."""
    tree = ast.parse(inspect.getsource(tur))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Tuple, ast.List, ast.Set, ast.FrozenSet if hasattr(ast, "FrozenSet") else ast.Set)):
            names = {e.value for e in node.elts
                     if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            assert not {"checkbox", "radio"} <= names, (
                "a second copy of the unfillable-input rule is back: %s" % sorted(names))


def test_the_runner_skips_with_the_shared_set():
    assert "if typ in _UNFILLABLE_INPUT_TYPES_670:" in _runner_fill_fn()


def test_the_runner_fills_typed_inputs_and_counts_them():
    """The per-input `except` swallowed the throw AND the fill, so `filled` under-reported."""
    fn = _runner_fill_fn()
    i = fn.index("if typ in _TYPED_INPUT_VALUES_1203ip:")
    after = fn[i:].splitlines()[1:4]
    assert any("_TYPED_INPUT_VALUES_1203ip[typ]" in l for l in after), after
    assert any("filled += 1" in l for l in after), after


def test_the_runner_does_not_clobber_a_value_from_an_earlier_step():
    """Staged forms re-enter this loop; the typed branch must sit AFTER the input_value guard."""
    fn = _runner_fill_fn()
    assert fn.index("input_value()") < fn.index("_TYPED_INPUT_VALUES_1203ip")


def test_the_pair_imports_in_either_order():
    """`test_user_validation` imports this module lazily, inside functions; a module-level
    import back would be a cycle if that ever changed."""
    import importlib
    import subprocess
    import sys
    mod = "env_generator.llm_generator.multi_agent.runtime."
    for first, second in ((mod + "test_user_runner", mod + "test_user_validation"),
                          (mod + "test_user_validation", mod + "test_user_runner")):
        code = ("import sys; sys.path.insert(0, %r)\n"
                "import importlib\n"
                "a = importlib.import_module(%r)\n"
                "b = importlib.import_module(%r)\n"
                "assert a._TYPED_INPUT_VALUES_1203ip is b._TYPED_INPUT_VALUES_1203ip\n"
                % (str(__import__("pathlib").Path(inspect.getfile(tur)).parents[5]),
                   first, second))
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
        assert r.returncode == 0, "%s then %s: %s" % (first, second, r.stderr[-400:])
    assert importlib  # the import above is the subject, not decoration


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded_beside_the_map():
    flat = " ".join(inspect.getsource(tuv).replace("#", " ").split())
    assert "11 ui_flow failures across" in flat
    assert "EVERY one is" in flat


def test_the_false_negative_is_named_as_such():
    """#670 wrote the same sentence for the checkbox; a reader must see the probe failed."""
    flat = " ".join(inspect.getsource(tuv).split())
    assert flat.count("The app was fine.") >= 2


def test_why_skipping_would_be_wrong_is_recorded():
    """The alternative treatment (#670's, for range/color) is rejected on purpose."""
    flat = " ".join(inspect.getsource(tuv).split())
    assert "stops exercising the thing it exists to exercise" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
