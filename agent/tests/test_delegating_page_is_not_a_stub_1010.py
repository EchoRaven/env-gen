"""#1010: a page that delegates to a component is finished work, not a stub.

r164's frontend lane wrote this LoginPage — correct, DRY, 612 bytes:

    import AuthForm from '../components/AuthForm';
    export default function LoginPage() {
      return <main className="auth-page"><AuthForm mode="login" /></main>;
    }

`_DEFINITIVE_STUB_MAX_BYTES` is 700, so it read as a stub and the projector overwrote it with a
72-line inline copy of the same form. **95 commits to that one file in a single run, 49 by the
lane and 46 by the framework, alternating 12 lines against 72.** The five "Restore six
registered UI pages" repair tasks are the downstream cost, and they inflate both the task count
and the wall clock.

The threshold was calibrated on two samples recorded in its own comment — r59's 103-line real
page and r61's 7-line `<h2>Landing</h2>` — both of the form "large = real, small = empty".
Nobody sampled SMALL AND REAL, which is exactly what a page looks like once its logic moves
into a component. **The rule rewarded verbosity and punished reuse.**

Structural, not size-based, and it errs toward "not a stub": missing a real stub costs one
unrepaired page, while the false positive deletes the lane's work every tick.
"""

import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _DEFINITIVE_STUB_MAX_BYTES, _is_definitive_stub_page)

R164_REAL = (
    "import AuthForm from '../components/AuthForm';\n"
    "import { Link } from 'react-router-dom';\n\n"
    "export default function LoginPage() {\n"
    "  return <main className=\"auth-page\">\n"
    "    <section className=\"auth-panel\" aria-label=\"Sign in\">\n"
    "      <AuthForm mode=\"login\" />\n"
    "    </section>\n"
    "  </main>;\n"
    "}\n")

EMPTY_STUB = "export default function LandingPage() {\n  return <h2>Landing</h2>;\n}\n"


def test_the_r164_page_is_not_a_stub():
    assert len(R164_REAL.encode()) < _DEFINITIVE_STUB_MAX_BYTES, (
        "the whole point is that it is UNDER the byte threshold")
    assert _is_definitive_stub_page(R164_REAL) is False


def test_a_real_stub_is_still_repaired():
    assert _is_definitive_stub_page(EMPTY_STUB) is True


def test_an_unrendered_import_does_not_excuse_a_stub():
    """Importing something and never using it is still a stub — the component must appear in
    the JSX, or any leftover import would whitelist an empty page."""
    text = ("import AuthForm from '../components/AuthForm';\n"
            "export default function P() { return <h2>Login</h2>; }\n")
    assert _is_definitive_stub_page(text) is True


def test_a_package_import_does_not_excuse_a_stub():
    """Only LOCAL components count. `import { Link } from 'react-router-dom'` is not evidence
    that the page was written."""
    text = ("import { Link } from 'react-router-dom';\n"
            "export default function P() { return <h2>Login</h2>; }\n")
    assert _is_definitive_stub_page(text) is True


def test_self_closing_and_open_tags_both_count():
    for jsx in ("<Widget />", "<Widget>x</Widget>"):
        text = (f"import Widget from './Widget';\n"
                f"export default function P() {{ return {jsx}; }}\n")
        assert _is_definitive_stub_page(text) is False


def test_large_pages_are_untouched_as_before():
    assert _is_definitive_stub_page("x" * (_DEFINITIVE_STUB_MAX_BYTES + 1)) is False


def test_the_control_calls_the_good_page_a_stub():
    """Planted control: the PRE-FIX rule was size plus markers, and r164's real page cleared
    neither bar."""
    assert len(R164_REAL.encode()) < _DEFINITIVE_STUB_MAX_BYTES
    assert "export default" in R164_REAL and "return" in R164_REAL, (
        "the control was supposed to satisfy the old stub test; if it does not, this fix is "
        "unmotivated")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


def test_a_compact_import_still_counts():
    """#1010a: `from'../x'` with no space is valid JS and r163's LandingPage uses it for three
    local components. The first regex demanded `\\s+` and let that real page through to be
    overwritten — caught by replaying 253 corpus pages, not by reading the pattern."""
    text = ("import LandingHeader from'../components/LandingHeader';\n"
            "export default function LandingPage(){ return <LandingHeader />; }\n")
    assert _is_definitive_stub_page(text) is False
