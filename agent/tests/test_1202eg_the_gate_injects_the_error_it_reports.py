r"""#1202eg: the capture throws into the app's console, then blames the app.

`add_init_script` runs on EVERY document the browser context loads, about:blank and any
opaque-origin document included. On those, touching `window.localStorage` raises --
Chrome words it "Failed to read the 'localStorage' property from 'Window': Access is
denied for this document" even for a setItem, because reading the PROPERTY is what is
denied.

The visual gate injects three such scripts. Only the theme one was wrapped:

    _theme_storage_js      try { ... } catch (e) {}      guarded since it was written
    _profile_select_init_js  localStorage.setItem(...)   unguarded
    token injection          localStorage.setItem(...)   unguarded

The Python `try/except` around each `add_init_script` guards only REGISTERING the script.
The throw happens later, in the browser, on documents nobody registered anything for.

tiktok-web-r96 logged that exact sentence on exactly the three screens that need auth --
messages_dm_empty, notifications_activity, profile_own -- which is where the token and
profile scripts are injected. #740 then recorded it as a page error and the deviation
told the lane "The browser reported: Failed to read the 'localStorage' property ... fix
THAT, it is the reason the shell is empty".

The framework was manufacturing an error and dispatching a lane to fix it.
"""
import sys
from pathlib import Path

import pytest

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

VF_PATH = (THIS_DIR.parent / "env_generator" / "llm_generator" / "multi_agent"
           / "runtime" / "visual_fidelity.py")
VF = VF_PATH.read_text(encoding="utf-8")


def test_the_profile_script_cannot_throw_on_a_denied_origin():
    from multi_agent.runtime.visual_fidelity import _profile_select_init_js
    js = _profile_select_init_js("p1")
    assert "localStorage" in js, "the script must still do its job"
    assert js.startswith("try {") and "catch" in js


def test_an_absent_profile_still_injects_nothing():
    from multi_agent.runtime.visual_fidelity import _profile_select_init_js
    assert _profile_select_init_js("") == ""
    assert _profile_select_init_js(None) == ""


def test_the_token_script_is_guarded_too():
    i = VF.index("_aliases = (\"token\", \"access_token\"")
    seg = VF[i:VF.index("page = await ctx.new_page()", i)]
    assert "_storage_guard_1202eg" in seg


def test_the_guard_keeps_the_body_intact():
    from multi_agent.runtime.visual_fidelity import _storage_guard_1202eg
    out = _storage_guard_1202eg("localStorage.setItem('k','v');")
    assert "localStorage.setItem('k','v');" in out
    assert out.startswith("try {") and out.rstrip().endswith("catch (e) {}")


def test_an_empty_body_produces_no_script():
    from multi_agent.runtime.visual_fidelity import _storage_guard_1202eg
    assert _storage_guard_1202eg("") == ""


def test_the_theme_script_was_always_right():
    """The precedent this fix copies -- it must not regress."""
    from multi_agent.runtime.visual_fidelity import _theme_storage_js
    assert _theme_storage_js("dark").startswith("try {")
    assert _theme_storage_js(None).startswith("try {")


def test_no_inline_storage_init_script_is_unguarded():
    """Every INLINE injection -- the shape both bugs had. A site that passes a variable
    (`add_init_script(_js)`) is invisible here by construction; those are covered by the
    builder's own test above, which is where the guard lives."""
    import re
    unguarded = []
    for m in re.finditer(r"add_init_script\(", VF):
        # the ARGUMENT, delimited by its own parentheses -- not a byte window (#943):
        # a fixed slice either misses a long argument or swallows the next statement.
        depth, i = 1, m.end()
        while i < len(VF) and depth:
            depth += (VF[i] == "(") - (VF[i] == ")")
            i += 1
        arg = VF[m.end():i - 1]
        if "localStorage" in arg and "_storage_guard_1202eg" not in arg:
            unguarded.append(VF[:m.start()].count("\n") + 1)
    assert not unguarded, f"unguarded storage init script(s) at line(s) {unguarded}"
