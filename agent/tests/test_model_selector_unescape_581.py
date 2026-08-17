r"""#581: a model composing a CSS selector inside a JSON tool argument naturally writes
``input[placeholder=\"Email or phone number\"]``. JSON decoding removes one level of escaping,
so what reaches the browser still carries backslashes and the engine rejects it outright:

    SyntaxError: Failed to execute 'querySelectorAll' on 'Document':
    'input[placeholder=\"Email or phone number\"]' is not a valid selector.

Mined offline from the run logs: 24 occurrences across the netflix arc — also
``input[aria-label=\"Email or mobile number\"]``, ``input[placeholder=\"Full name\"]``,
``input[placeholder=\"Email or mobile number\" i]``. Each is a wasted browser step whose error
tells the model nothing about the page (the very problem #362's candidate listing exists to
solve, defeated here because the failure is a syntax error, not a miss).
"""
import pytest

from env_generator.llm_generator.tools.browser import interaction as bi

_f = bi._unescape_model_selector


def test_the_four_shapes_seen_in_the_logs():
    for bad, good in (
        (r'input[placeholder=\"Email or phone number\"]',
         'input[placeholder="Email or phone number"]'),
        (r'input[aria-label=\"Email or mobile number\"]',
         'input[aria-label="Email or mobile number"]'),
        (r'input[placeholder=\"Full name\"]', 'input[placeholder="Full name"]'),
        (r'input[placeholder=\"Email or mobile number\" i]',
         'input[placeholder="Email or mobile number" i]'),
    ):
        assert _f(bad) == good, bad


def test_single_quote_escapes_too():
    assert _f(r"button[type=\'submit\']") == "button[type='submit']"


def test_a_correct_selector_is_untouched():
    for s in ('#login-btn', 'button[type=submit]', "input[name='username']",
              'input[placeholder="Email"]', '[data-testid="x"]', 'a[href]'):
        assert _f(s) == s, s


def test_a_legitimate_css_escape_survives():
    """`.foo\\:bar` escapes a colon in a class name — not our business to strip."""
    for s in (r'.foo\:bar', r'.a\/b', r'.x\\y'):
        assert _f(s) == s, s


def test_empty_and_none_are_safe():
    assert _f('') == ''
    assert _f(None) == ''


def test_both_click_and_fill_apply_it():
    """Two entry points take a model-authored selector; both must sanitise."""
    import inspect
    src = inspect.getsource(bi)
    assert src.count('_unescape_model_selector(') >= 3, "click + fill + the def"
    fill = inspect.getsource(bi.BrowserFillTool.execute)
    assert '_unescape_model_selector(selector)' in fill, fill


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
