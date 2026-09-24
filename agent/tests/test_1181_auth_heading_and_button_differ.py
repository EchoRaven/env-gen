"""#1181 — the auth page's heading and its submit button carried the SAME text.

netflix r18's last blocker was `validation:ui_flow:signup_to_browse`:

    "Post-remediation rerun still stayed on /signup after Create account;
     no console/network errors."

The flow works. Driving a real browser against the delivered r18 stack: fill
input[name='email'] / [name='password'], click the button whose ROLE is button and whose
name is "Create account" -> POST /auth/register 201 -> the page navigates to /browse, with
no console errors. What the browser also reports is the cause:

    elements with text "Create account": 2
    of those, role=button:               1

The `<h1>` and the submit `<button>` both read "Create account", so a walk that locates the
control by TEXT rather than by ROLE can click the heading -- which does nothing, navigates
nowhere and issues no request. That is precisely the recorded symptom, and it cost r18 its
delivery.

The template already had the right pattern for the other state -- heading "Sign in", button
"Log in" -- so the register branch now follows it: heading names the page ("Sign up"), the
button names the action ("Create account"). Searching for the action text now finds exactly
one element, and it is the button.

Present in r13, r14, r17 and r18 alike; it bit once, and once was a whole run.
"""
import re

import env_generator.llm_generator.multi_agent.runtime.frontend_scaffold as fs

_SRC = open(fs.__file__).read()


def _auth_form_span():
    """The auth template's form, cut at its own </form> landmark — not a byte window."""
    i = _SRC.index("{isRegister ? 'Create account' : 'Log in'}")
    start = _SRC.rindex("<h1", 0, i)
    return _SRC[start:_SRC.index("</form>", i)]


def _ternary_pair(span, tag):
    m = re.search(r"\{isRegister \? '([^']+)' : '([^']+)'\}", span[span.index(tag):])
    assert m, f"no isRegister ternary after {tag}"
    return m.group(1), m.group(2)


def test_heading_and_submit_differ_in_both_states():
    span = _auth_form_span()
    h_reg, h_login = _ternary_pair(span, "<h1")
    b_reg, b_login = _ternary_pair(span, 'type="submit"')
    assert h_reg != b_reg, (
        f"register heading and button both read {h_reg!r} — a text-located click is ambiguous")
    assert h_login != b_login, f"login heading and button both read {h_login!r}"


def test_the_action_label_is_on_the_button():
    """A walk searching for the ACTION text must land on the control that performs it."""
    span = _auth_form_span()
    _, _ = _ternary_pair(span, "<h1")
    b_reg, _ = _ternary_pair(span, 'type="submit"')
    heading = span[span.index("<h1"):span.index("</h1>")]
    assert b_reg not in heading, f"the heading still repeats the button's label {b_reg!r}"


def test_the_toggle_does_not_reuse_the_submit_label():
    """The mode toggle is the other button on this form; it must not collide either."""
    span = _auth_form_span()
    b_reg, b_login = _ternary_pair(span, 'type="submit"')
    toggle = span[span.index('type="button"'):] if 'type="button"' in span else ""
    for label in (b_reg, b_login):
        assert f"'{label}'" not in toggle, f"the toggle repeats the submit label {label!r}"
