r"""#670: a "Remember me" checkbox made the probe report a working login form as broken.

`test_user_reports/` — 99 JSON files across 70 runs — is the standing goal's own instrument, and
it had never been opened. Aggregating it:

    signup flow   66/66 pass
    login  flow   54/66 pass  — 12 failures

The asymmetry looks like a login-wiring bug, and 8 of the 12 are exactly that. Two are not:

    r128  Locator.fill: Input of type "checkbox" cannot be filled
          — waiting for locator("input").nth(2)
    r142  "the form IS wired but /auth returned 401" — already self-diagnosed, correctly

The probe fills visible inputs by placeholder/type, and its final `else` fills EVERY
unrecognised one with a text string. A "Remember me" checkbox lands there. Only `is_visible()`
was guarded, not the fill, so the exception aborted the flow and the report read *"UI login:
submit did nothing — the form is not wired to the API"*. The app was fine.

Measured: 10 of the 208 delivered login pages carry a checkbox, so each is a false negative
waiting to fire. Skipping the types `fill()` refuses cannot hide a real defect — a form whose
EMAIL or PASSWORD field is unfillable still fails exactly as it did before.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime import test_user_validation as tuv

SKIP = tuv._UNFILLABLE_INPUT_TYPES_670


# --- the types that broke it ------------------------------------------------------------------

def test_checkbox_is_skipped():
    """r128, verbatim: Input of type "checkbox" cannot be filled."""
    assert "checkbox" in SKIP


@pytest.mark.parametrize("typ", ["checkbox", "radio", "submit", "button", "reset",
                                 "image", "file", "hidden", "range", "color"])
def test_every_unfillable_html_type_is_skipped(typ):
    assert typ in SKIP


# --- the types the flow depends on must NOT be skipped ---------------------------------------------

@pytest.mark.parametrize("typ", ["email", "password", "text", "tel", "search", "url", "number", ""])
def test_the_fillable_types_are_untouched(typ):
    """Skipping any of these would silence a real wiring failure."""
    assert typ not in SKIP


def test_an_input_with_no_type_attribute_is_still_filled():
    """`<input>` defaults to text; the probe reads "" for a missing attribute."""
    assert "" not in SKIP


# --- shape ------------------------------------------------------------------------------------

def test_the_set_is_immutable():
    assert isinstance(SKIP, frozenset)


def test_it_holds_only_lowercase_names():
    """The caller lowercases the attribute before the lookup."""
    assert all(t == t.lower() for t in SKIP)


def test_it_contains_no_product_literals():
    """Every entry must be a standard HTML input type."""
    html = {"button", "checkbox", "color", "date", "datetime-local", "email", "file", "hidden",
            "image", "month", "number", "password", "radio", "range", "reset", "search",
            "submit", "tel", "text", "time", "url", "week"}
    assert SKIP <= html


# --- wiring -------------------------------------------------------------------------------

def _fill_block():
    """The fill loop, bounded by the construct that follows it."""
    import inspect
    src = inspect.getsource(tuv)
    i = src.index("async def _fill_visible_inputs")
    return src[i:src.index("# Up to 3 fill+submit rounds", i)]


def test_the_guard_runs_before_any_branch_that_fills():
    body = _fill_block()
    assert "if typ in _UNFILLABLE_INPUT_TYPES_670:" in body
    assert body.index("_UNFILLABLE_INPUT_TYPES_670") < body.index('if "email" in ph')


def test_it_continues_rather_than_returning():
    """One skipped input must not end the sweep over the rest of the form."""
    body = _fill_block()
    i = body.index("if typ in _UNFILLABLE_INPUT_TYPES_670:")
    assert body[i:].lstrip().splitlines()[1].strip() == "continue"


def test_the_type_is_lowercased_before_the_lookup():
    body = _fill_block()
    assert 'get_attribute("type")) or "").lower()' in body


def test_the_catch_all_else_is_still_there():
    """#670 narrows what reaches the else; it must not remove the else."""
    body = _fill_block()
    assert "else:" in body


# --- provenance -------------------------------------------------------------------------------

def test_the_measurement_is_recorded():
    import inspect
    flat = " ".join(inspect.getsource(tuv).replace("#", " ").split())
    assert "12 of 66 test-user reports fail the login flow" in flat
    assert "10 of the 208 delivered login pages carry a checkbox" in flat


def test_the_false_negative_is_named_as_such():
    """The next reader must see this was the PROBE failing, not the app."""
    import inspect
    flat = " ".join(inspect.getsource(tuv).split())
    assert "The app was fine." in flat


def test_why_skipping_is_safe_is_recorded():
    import inspect
    flat = " ".join(inspect.getsource(tuv).split())
    assert "still fails exactly as before" in flat


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
