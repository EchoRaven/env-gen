"""#1179 — a class placeholder shipped, literally, into three delivered apps.

`_auth_page_classes` is applied in ONE pass, but one of its own values carries a
placeholder: `_auth_extras_873` supplies `__EXTRA_NOTICE__` as
`<p className="pt-1 text-xs __CLS_LINK__" ...>`, and `**_auth_extras_873(design)` sits last
in the dict literal, so `__CLS_LINK__` is substituted BEFORE the notice injects a fresh one.
Nothing revisits it.

netflix r13, r14 and r17 each carry `<p className="pt-1 text-xs __CLS_LINK__">` in
SignupPage.jsx; it survives the vite build into the bundle (confirmed by fetching
/assets/index-*.js off the running r17 stack), so the browser renders
class="pt-1 text-xs __CLS_LINK__" on the signup form of every delivered app.
"""
import re

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _apply_auth_classes_1179, _auth_page_classes,
)

_TOKEN = re.compile(r"__[A-Z][A-Z0-9_]{2,}__")


def test_a_value_that_carries_a_placeholder_is_resolved():
    """The exact shape of the defect, in miniature."""
    mapping = {
        "__CLS_LINK__": "text-blue-600",
        "__EXTRA_NOTICE__": '<p className="pt-1 text-xs __CLS_LINK__">note</p>',
    }
    out = _apply_auth_classes_1179("<div>__EXTRA_NOTICE__</div>", mapping)
    assert "__CLS_LINK__" not in out, "the injected placeholder must be resolved too"
    assert "text-blue-600" in out


def test_one_pass_would_not_have_caught_it():
    """★ Plant the defect and demand the finding — pins that the fix is the ITERATION."""
    mapping = {
        "__CLS_LINK__": "text-blue-600",
        "__EXTRA_NOTICE__": '<p className="__CLS_LINK__">note</p>',
    }
    src = "<div>__EXTRA_NOTICE__</div>"
    one_pass = src
    for ph, cls in mapping.items():          # the pre-#1179 loop, verbatim
        one_pass = one_pass.replace(ph, cls)
    assert "__CLS_LINK__" in one_pass, "single-pass must still show the bug"
    assert "__CLS_LINK__" not in _apply_auth_classes_1179(src, mapping)


def test_cross_map_injection_is_resolved():
    """Site 1 applies two maps; a value in either may carry the other's placeholder."""
    page = {"__CLS_LINK__": "accent"}
    footer = {"__FOOT__": '<a className="__CLS_LINK__">x</a>'}
    out = _apply_auth_classes_1179("<i>__FOOT__</i>", page, footer)
    assert "__CLS_LINK__" not in out and "accent" in out


def test_the_real_class_map_leaves_no_token_behind():
    """With the framework's own map, an auth page carrying every placeholder resolves clean."""
    mapping = _auth_page_classes(None)
    src = " ".join(sorted(mapping)) + " __EXTRA_NOTICE__"
    out = _apply_auth_classes_1179(src, mapping)
    left = sorted(set(_TOKEN.findall(out)) - {"__EXTRA_NOTICE__"})
    assert not left, f"unsubstituted class token(s) would ship: {left}"


def test_it_terminates_on_a_self_referential_value():
    """Bounded: a value naming itself must not spin the scaffolder."""
    out = _apply_auth_classes_1179("__LOOP__", {"__LOOP__": "x __LOOP__"})
    assert out.count("__LOOP__") <= 1
