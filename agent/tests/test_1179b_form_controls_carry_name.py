"""#1179b — a working signup form recorded as broken because its inputs had no `name`.

netflix r17's final blocker was `validation:ui_flow:signup`:

    "/signup loaded but input[name='email'] was not present/interactable;
     page exposed app-shell controls instead of signup form."

The form was fine. SignupPage.jsx renders a wordmark header, Name / Email / Password
inputs, a submit button and a sign-in toggle, and POST /api/auth/register returns 201 with
an access_token when probed directly. What it did NOT have was a `name` attribute on any
input -- the framework's own auth template emits `type` and `placeholder` only -- so the
verifier's `input[name='email']` selector found nothing and it recorded a product failure.
That record blocked delivery on a working app.

`name` on a form control is correct HTML regardless (browsers, password managers and
autofill all key on it), it is inert for a React controlled input, and it removes a class of
false gate failures for every env the scaffolder builds.
"""
import re

import env_generator.llm_generator.multi_agent.runtime.frontend_scaffold as fs

_SRC = open(fs.__file__).read()


def _auth_template_inputs():
    """Every `<input` the scaffolded AUTH templates emit, cut at the enclosing form's end —
    landmark-anchored, never a byte window (#943)."""
    out = []
    for m in re.finditer(r"setPassword\(e\.target\.value\)", _SRC):
        start = _SRC.rindex("<form", 0, m.start())
        end = _SRC.index("</form>", m.start())
        out.extend(re.findall(r"<input\b[^>]*", _SRC[start:end]))
    return out


def test_the_auth_templates_emit_named_controls():
    inputs = _auth_template_inputs()
    assert len(inputs) >= 4, f"expected the auth templates' controls, found {len(inputs)}"
    unnamed = [i for i in inputs if not re.search(r"\bname\s*=", i)]
    assert not unnamed, (
        "an auth control with no name= is invisible to input[name='...'] — the selector the "
        "verifier walk uses:\n" + "\n".join(x[:110] for x in unnamed))


def test_email_and_password_are_named_by_those_words():
    """The walk selects `input[name='email']` specifically, not just any name."""
    joined = " ".join(_auth_template_inputs())
    assert 'name="email"' in joined
    assert 'name="password"' in joined


def test_the_landing_email_capture_is_named_too():
    """The landing hero's 'Get Started' form is a real form and takes a real address."""
    i = _SRC.index('aria-label=\\"Email address\\"')
    tag_start = _SRC.rindex("<input", 0, i)
    assert 'name=\\"email\\"' in _SRC[tag_start:i]
