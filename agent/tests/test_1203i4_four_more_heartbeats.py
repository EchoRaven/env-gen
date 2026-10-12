"""#1203i4: four more warnings that printed a line per tick for a state that had not moved.

After #1203i2 and #1203i3 took the top two, re-ranking the framework's `[W]` lines by volume
over the last 13 runs -- and counting DISTINCT messages, which is what separates a report
from a heartbeat -- left four:

    handler FK-alias repair DECLINED      1680 lines, 3-8 distinct/run, 35-63 repeats each
    Pre-validation merge: nothing...       558 lines, 2 distinct/run,   29-45 repeats each
    Framework delivery writes COMMITTED    433 lines, ONE distinct,     45-52 repeats
    #1202vz declared FK no row fills       319 lines in r180 alone, ONE distinct

2990 lines saying four things. Each is an order of magnitude smaller than #1203i2's 14791 or
#1203i3's 17620, which is why they are ONE patch rather than four: the fix is identical and
the measurement is the same shape.

The item goes in the SITE key and the state is a constant marker, because what differs
between these reports is which model / lane / column they are about -- never a value whose
movement is news. That is the opposite of #1203i3, where the drop COUNT moves and its order
of magnitude is the state; both choices come from asking what would be new information.
"""
from __future__ import annotations

import ast
import inspect
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import heal_pipeline as _heal  # noqa: E402
from multi_agent.runtime import material_prep as _mat  # noqa: E402
from multi_agent.runtime.message_format import reset_state_memo_1202ad  # noqa: E402

#: every emitter this patch guards, by a phrase only that emitter says
GUARDED = {
    "handler FK-alias repair DECLINED": _heal,
    "Framework delivery writes COMMITTED": _heal,
    "Pre-validation merge agent/%s": _heal,
    "is a declared FK to `%s` that NO dataset row fills": _mat,
}


@pytest.fixture(autouse=True)
def _fresh():
    for pre in ("heal.", "material_prep."):
        reset_state_memo_1202ad(pre)
    yield
    for pre in ("heal.", "material_prep."):
        reset_state_memo_1202ad(pre)


# ------------------------------------------------------------------ the helper contract


@pytest.mark.parametrize("mod", [_heal, _mat])
def test_it_says_an_item_once(mod):
    """★ The two helpers share ONE global memo (`#1202ad`'s `_STATE_SAID_1202AD`), so every
    site string has to be globally unique -- the first draft of this test used `site.a` in
    both parametrised runs and the second read as already-said. That is also why the real
    sites are prefixed `heal.` and `material_prep.`."""
    say = mod._say_once_1203i4
    site = "t.once.%s" % mod.__name__
    assert say(site, "Notification") is True
    assert say(site, "Notification") is False
    assert say(site, "Notification") is False


@pytest.mark.parametrize("mod", [_heal, _mat])
def test_two_items_do_not_silence_each_other(mod):
    say = mod._say_once_1203i4
    site = "t.items.%s" % mod.__name__
    assert say(site, "Notification") is True
    assert say(site, "Follow") is True
    assert say(site, "Notification") is False


@pytest.mark.parametrize("mod", [_heal, _mat])
def test_two_sites_are_independent(mod):
    say = mod._say_once_1203i4
    assert say("t.c.%s" % mod.__name__, "x") is True
    assert say("t.d.%s" % mod.__name__, "x") is True


@pytest.mark.parametrize("mod", [_heal, _mat])
def test_a_memo_failure_returns_true_rather_than_silencing(mod, monkeypatch):
    import builtins
    real = builtins.__import__

    def no_memo(name, *a, **k):
        if "message_format" in name:
            raise ImportError("memo unavailable")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_memo)
    say = mod._say_once_1203i4
    site = "t.boom.%s" % mod.__name__
    assert say(site, "x") is True
    assert say(site, "x") is True, "a memo failure silenced the second report"


@pytest.mark.parametrize("mod", [_heal, _mat])
def test_junk_items_cannot_raise(mod):
    say = mod._say_once_1203i4
    for junk in (None, 0, [], {}, object()):
        assert isinstance(say("t.junk.%s" % mod.__name__, junk), bool), junk


# ---------------------------------------------------------- every emitter is guarded


def _calls_saying(tree, phrase):
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        if any(isinstance(c, ast.Constant) and isinstance(c.value, str)
               and phrase in c.value for c in ast.walk(n)):
            out.append(n)
    return out


@pytest.mark.parametrize("phrase,mod", list(GUARDED.items()))
def test_the_emitter_is_behind_the_memo(phrase, mod):
    """★ Four sites, one assertion: the warning must be reachable only through an `if` whose
    test calls `_say_once_1203i4`. A fifth emitter added later without the guard turns this
    red, which a per-site fixture would not."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(mod)))
    emitters = [c for c in _calls_saying(tree, phrase)
                if isinstance(c.func, ast.Attribute)
                and c.func.attr in ("warning", "error")]
    assert emitters, "found no warning emitting %r" % phrase
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if not any(isinstance(c, ast.Call)
                   and getattr(c.func, "id", None) == "_say_once_1203i4"
                   for c in ast.walk(node.test)):
            continue
        emitters = [e for e in emitters
                    if e not in [n for n in ast.walk(node)]]
    assert emitters == [], (
        "%d emitter(s) of %r are not behind the memo" % (len(emitters), phrase))


@pytest.mark.parametrize("phrase,mod", list(GUARDED.items()))
def test_the_site_key_carries_the_item(phrase, mod):
    """A constant site would make one model/lane/column silence every other."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(mod)))
    guards = [c for c in ast.walk(tree)
              if isinstance(c, ast.Call)
              and getattr(c.func, "id", None) == "_say_once_1203i4"]
    assert guards, "no guard calls at all"
    for g in guards:
        assert len(g.args) == 2, ast.dump(g)
        item = g.args[1]
        assert not (isinstance(item, ast.Constant) and item.value in ("", None)), ast.dump(g)


# ------------------------------------------------------------- the words are unchanged


def test_every_sentence_survives():
    heal = inspect.getsource(_heal)
    mat = inspect.getsource(_mat)
    for phrase in ("handler FK-alias repair DECLINED (ambiguous owner)",
                   "Left as an AttributeError 500 on purpose",
                   "release snapshot ships them (skeleton/infra/projections)",
                   "surfaced committed code the lane had not finish-merged"):
        assert phrase in heal, phrase
    for phrase in ("that NO dataset row fills",
                   "an ambiguous natural key is refused outright"):
        assert phrase in mat, phrase


def test_the_two_helpers_are_deliberate_copies_not_an_import_cycle():
    """`material_prep` keeps its own four-line copy rather than importing heal_pipeline's,
    because heal_pipeline imports this module's siblings. The SHARED part is the memo, in
    #1202ad -- pin that both go through it, so a future edit cannot fork the behaviour."""
    for mod in (_heal, _mat):
        src = inspect.getsource(mod._say_once_1203i4)
        assert "state_changed_1202ad" in src, mod.__name__
        assert "return True" in src, mod.__name__
