r"""#1203e5: the structured verdict was flattened to English exactly where its consumer reads.

`chain_executor` classifies a chain step whose request never reached the app as
`kind == "environment_1202od"`, and `validation_runner`'s comment on that branch says why it
bothers: "the steps never reached the app. Not a pass (nothing was verified) and not the lanes'
failure — say which it is, SO THE RETRY IS THE REMEDY."

`_add(name, ok, detail)` then stored only `{name, status, detail}`, so the verdict survived into
the check record as an English sentence and nothing else:

    "NOT VERIFIED — the app was unreachable while the chains ran ... This is the stack, not the
     code: no lane edit can change it. Re-run the validation once the stack is up."

`ensure_fresh_smoke_before_cut` is the component that decides whether to retry. It could not
read that, so it took the latch path: `_fresh_smoke_fail_sig = cur`, and `fresh_smoke_decision`
then returns "hold" for that exact signature **until the BACKEND SOURCE changes** — demanding
precisely the lane edit the sentence rules out. A ledger entry whose stated remedy the code
cannot honour is the same defect as #1203d4, #1203d5 and #1203d7.

★ Live: r152 wrote that hold at 23:45:34, and it is the ONLY hold record in the whole corpus
carrying the sentence — because #1203d5 widened this line's evidence budget from 60 characters
to 300 six hours earlier. The verdict itself fires regularly: 39 gate records of
`business_chain_environment_blocked` across 7 runs (r147 21, r136 6, r144 5, r132 3, r126 2,
r146 1, r152 1), every earlier one cut off before the sentence.

★ HONEST LIMIT, pinned by a test below: this changes the decision only when EVERY failing check
is exonerated. r152's own tick also failed `frontend_reachable`, whose own comment says a
container that "crashed after start" can be the nginx env-var bug — genuinely the code's — so
r152 would still have held. "Two services unreachable means the stack is down" is a predicate I
would be inventing, and it is not applied here.
"""
import inspect
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime import framework_validation as FV  # noqa: E402
from multi_agent.runtime import validation_runner as VR  # noqa: E402


# ---------------------------------------------------------------- the fact is carried

def _add_src():
    src = inspect.getsource(VR)
    i = src.index("    def _add(name: str, ok: bool")
    j = src.index("checks.append(_rec)", i) + len("checks.append(_rec)")
    return src[i:j]


def test_add_can_carry_a_structured_kind():
    s = _add_src()
    assert "kind: str" in s, s
    assert '_rec["kind"] = kind' in s, s


def test_an_empty_kind_leaves_the_record_shape_untouched():
    """★ The invariant: every other `_add` call site keeps producing exactly three keys, which is
    what 8418 recorded checks on disk look like."""
    s = _add_src()
    assert "if kind:" in s, "the key is added unconditionally, changing every other record:\n" + s


def test_the_environment_branch_passes_the_kind():
    """The one producer of the verdict must hand it over, not just describe it."""
    src = inspect.getsource(VR)
    i = src.index("This is the stack, ")
    j = src.index("_add(", i) if "_add(" in src[i:] else len(src)
    stanza = src[src.rindex("_add(", 0, i):i + 400]
    assert 'kind="environment_1202od"' in stanza, stanza


# ---------------------------------------------------------------- the consumer reads it

def _exon():
    """The exoneration helper, reached through the function that defines it."""
    src = inspect.getsource(FV.ensure_fresh_smoke_before_cut)
    assert "_not_the_apps_1203e5" in src, src
    ns = {"docker_up_host_fault_1202de": lambda d: ""}
    i = src.index("            def _not_the_apps_1203e5(c):")
    j = src.index("_why1203d5 = [", i)
    import textwrap
    exec(compile(textwrap.dedent(src[i:j]), "<exon>", "exec"), ns)
    return ns["_not_the_apps_1203e5"]


def test_an_environment_flagged_check_is_exonerated():
    """★ The defect in one assertion."""
    assert _exon()({"name": "business_chain", "status": "fail",
                    "kind": "environment_1202od", "detail": "NOT VERIFIED — ..."})


def test_an_ordinary_failing_check_is_not_exonerated():
    """★ The invariant: a real chain failure must still latch the tree."""
    assert not _exon()({"name": "business_chain", "status": "fail",
                        "detail": "GET /api/videos/10 → 404 (expected 200)"})


def test_frontend_reachable_is_not_exonerated():
    """★ The stated limit, pinned: r152's second failing check stays the app's, so r152 would
    still have held. If someone later exempts it, this test makes them say so."""
    assert not _exon()({"name": "frontend_reachable", "status": "fail",
                        "detail": "GET :8024/ → URLError: <urlopen error [Errno 111] Connection "
                                  "refused> — the frontend container is not serving "
                                  "(crashed after start?)"})


def test_the_host_fault_path_still_works():
    """#1203d5's original route must survive: the classifier's answer is still honoured."""
    src = inspect.getsource(FV.ensure_fresh_smoke_before_cut)
    import textwrap
    ns = {"docker_up_host_fault_1202de": lambda d: "no space left on device" if "space" in str(d) else ""}
    i = src.index("            def _not_the_apps_1203e5(c):")
    j = src.index("_why1203d5 = [", i)
    exec(compile(textwrap.dedent(src[i:j]), "<exon>", "exec"), ns)
    f = ns["_not_the_apps_1203e5"]
    assert f({"detail": "docker_up: no space left on device"}) == "no space left on device"


def test_a_malformed_check_does_not_raise():
    f = _exon()
    for c in (None, {}, {"kind": None}, {"kind": 7}):
        assert not f(c)


def test_the_kind_must_match_exactly():
    """Not a substring test: a different kind is not this verdict."""
    assert not _exon()({"kind": "broken"})
    assert not _exon()({"kind": "environment"})


def test_exoneration_requires_every_failing_check():
    """★ The composition with #1203d5: one unexplained failure and the tree latches as before.
    Pinned on the shipped source rather than re-implemented."""
    src = inspect.getsource(FV.ensure_fresh_smoke_before_cut)
    assert "if _fails1203d5 and all(_why1203d5):" in src, src


def test_the_limit_is_written_down_where_it_applies():
    """#1202zz: a decision whose reason is not in the code gets re-litigated — and here the
    LIMIT is the part a later reader will want to widen."""
    src = inspect.getsource(FV.ensure_fresh_smoke_before_cut)
    assert "HONEST LIMIT" in src and "frontend_reachable" in src, src[-900:]
