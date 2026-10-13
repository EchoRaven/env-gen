"""#1203ik — the chains said the verdict could not be trusted, then handed it to the gate.

`build_currency_1202ex` compares the source on disk against the image the stack is running,
and `chain_executor` logs the answer one line BEFORE running the chains:

    #1202ex: chains are about to judge an app whose image may not be the source on disk --
    app/ has changed since the image was built (source fa236080a838, built 593a8566a717) --
    the container may predate the handler under test; rebuild AND recreate the stack before
    trusting these results

It says the results cannot be trusted and then the next statement is
`results = [execute_chain(...) for ch in chains]`. 31-47 times per run across r182-r185, and
both directions cost: a chain that FAILS on stale code sends remediation to fix a defect the
new source may no longer have, and one that PASSES on stale code clears the gate for code
nobody tested.

Same shape as #1202od one branch down — "not a pass (nothing was verified) and not the lanes'
failure — say which it is, so the retry is the remedy" — but a DIFFERENT remedy, hence a
different kind: a transport failure is retried, a stale image must be rebuilt AND recreated.
Reusing `environment_1202od` would tell the agent to retry against the same old container
forever.

The check still reports False. The steps did fail; what changes is that the detail the
remediation task is built from now names the stack as a suspect before the code.
"""
import ast
import os
import pathlib
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _AGENT)

VR = pathlib.Path(
    _AGENT, "env_generator/llm_generator/multi_agent/runtime/validation_runner.py")


def _ik_block() -> str:
    """Between landmarks, not a byte window (#943)."""
    src = VR.read_text(encoding="utf-8")
    start = src.index("#1203ik: SAY THAT THESE STEPS MAY HAVE JUDGED THE OLD CODE")
    end = src.index("elif _chain.get(\"environment_1202od\")", start)
    return src[start:end]


def _ik_code() -> str:
    return "\n".join(ln for ln in _ik_block().splitlines()
                     if not ln.strip().startswith("#"))


def test_the_currency_verdict_is_read_from_its_owner():
    """#1032: one owner for the predicate. The answer must come from
    `build_currency_1202ex`, not from a second comparison invented here."""
    code = _ik_code()
    assert "build_currency_1202ex" in code
    assert '"changed"' in code, "the verdict compared against must be the owner's own value"


def test_the_field_names_match_what_the_owner_returns():
    """★ #1148 records that guessing a row's field names was "the fourth field-name miss of
    this session's lineage". `build_currency_1202ex` documents
    `{"verdict": ..., "detail": str}` — assert against the owner, so a rename there fails
    here instead of silently rendering an empty note."""
    ce = pathlib.Path(
        _AGENT, "env_generator/llm_generator/multi_agent/runtime/chain_executor.py"
    ).read_text(encoding="utf-8")
    assert 'return {"verdict": "changed",' in ce, (
        "build_currency_1202ex's return shape moved; #1203ik reads .get('verdict')/.get('detail')")
    code = _ik_code()
    assert '.get("verdict")' in code and '.get("detail")' in code


def test_the_detail_puts_the_stack_before_the_code():
    """The whole point: the remediation task is built from this detail, so it has to say
    rebuild-first rather than let the reader treat a stale verdict as a code defect."""
    blk = _ik_block()
    assert "STACK FIRST, THEN CODE" in blk
    assert "do not edit code to satisfy it" in blk, (
        "the one conclusion the owner's detail does NOT draw must be stated")
    # ★ and it must NOT restate what the owner already says. Driving this with r186's real
    # verdict showed the first wording repeating "app/ has changed" twice and "rebuild and
    # recreate" three times — #1202vx: the explanation must not spend the evidence budget.
    code = _ik_code()
    assert "app/ has changed" not in code, "the note restates the owner's own detail"
    assert "REBUILD AND RECREATE" not in code, (
        "the owner's detail already ends in 'rebuild AND recreate the stack'")
    # ★ and the quoted sentence must be terminated. build_currency_1202ex's `changed` detail
    # ends "...before trusting these results" with NO period, so quoting it inline ran two
    # sentences together. The unit fixture ended in a period and hid it; a real run's verdict
    # showed it.
    assert 'endswith((".", "!", "?"))' in code, (
        "the quoted verdict is not terminated, so it runs into the next sentence")
    # ★ and the original detail must REACH the message — this annotates, it does not
    # replace. Asserting only that `_business_chain_detail(` is called left a mutation
    # green that formatted the note with an empty body: the call existed, its result was
    # dropped. Pin the interpolation itself.
    code = _ik_code()
    assert "_business_chain_detail(" in code
    # Bound to the LAST interpolated argument, not to the first one's name: the first is the
    # terminated copy of the owner's verdict and was renamed once already. What must hold is
    # that the real failure text still reaches the message.
    assert ", _detail1203ik)" in code, (
        "the annotated detail does not interpolate the real failure text, so the steps "
        "that actually broke would not be reported")
    assert "_stale1203ik" in code, "the note no longer quotes the owner's verdict"


def test_the_kind_is_its_own_and_not_the_transport_one():
    """★ Reusing #1202od's kind would prescribe the WRONG remedy: retry against the same
    stale container. The remedies differ, so the kinds must."""
    code = _ik_code()
    assert 'kind="stale_image_1203ik"' in code
    assert "environment_1202od" not in code, (
        "the stale-image branch borrowed the transport kind, whose remedy is a retry")


def test_the_check_still_fails_and_is_not_whitewashed():
    """A stale image does not make a failing chain pass. #1023's lesson runs the other way
    too: this must not become a free pass at the gate."""
    code = _ik_code()
    assert '_add("business_chain", False' in code
    assert '_add("business_chain", True' not in code


def test_the_annotation_only_applies_when_the_image_is_stale():
    """A `current` or `unknown` verdict must leave the detail and the kind exactly as they
    were — `unknown` especially, since #1202ex's own helper returns it when there is no
    compose file or no fingerprint to compare, and that is not evidence of staleness."""
    code = _ik_code()
    assert 'if _stale1203ik:' in code
    assert 'kind="stale_image_1203ik" if _stale1203ik else ""' in code


def test_a_failure_in_the_probe_is_announced_not_swallowed():
    """#1202ah: an empty default from a swallowed exception reads downstream as "the image
    is fine", i.e. a crashed probe reporting a pass."""
    # On the CODE, not the block: a `warn_once_1201` mentioned in a comment would satisfy
    # a raw-text assertion. (The first attempt at mutating this away used a regex that
    # silently matched nothing — a mutation script that fails is not a mutation caught.)
    code = _ik_code()
    assert "warn_once_1201" in code
    assert "except Exception as _e1203ik:" in code, (
        "the probe's exception is no longer bound, so nothing can be announced")


def test_the_branch_is_reachable_in_the_broken_chain_path():
    """Pinned over the AST: the annotation has to sit on the branch that reports a BROKEN
    chain, which is the one that builds remediation — not somewhere unreachable."""
    src = VR.read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "_add"):
            continue
        if not (node.args and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "business_chain"):
            continue
        kw = {k.arg: ast.get_source_segment(src, k.value) or "" for k in node.keywords}
        if "stale_image_1203ik" in (kw.get("kind") or ""):
            # it must be the False (failing) call
            assert isinstance(node.args[1], ast.Constant) and node.args[1].value is False
            found = True
    assert found, "no _add('business_chain', False, ..., kind=stale_image_1203ik) call exists"


def test_the_stale_kind_is_not_mistaken_for_an_exoneration():
    """★ A stale image must NOT clear the tick the way #1202od does.

    `_not_the_apps_1203e5` exonerates a whole failing tick when every failure is "not the
    app's", and it recognises exactly `environment_1202od` — the chains never REACHED the
    app, so nothing was judged. A stale image is a different kind: the chains DID reach the
    app and DID judge code, just an older copy. A failure on the old handler may still be
    present in the new source, so clearing it wholesale would whitewash real defects.

    Pinned because the tempting "fix" for #1203ik's kind having no consumer is to add it to
    that helper, and that would be the wrong consumer. The right one is a rebuild+recreate
    before the next validation — not an exoneration, and not a retry (which is #1202od's
    remedy and would re-run against the same container).
    """
    import pathlib
    fv = pathlib.Path(
        _AGENT, "env_generator/llm_generator/multi_agent/runtime/framework_validation.py"
    ).read_text(encoding="utf-8")
    start = fv.index("def _not_the_apps_1203e5")
    body = fv[start:start + 600]
    assert "environment_1202od" in body, "the exoneration helper changed shape"
    assert "stale_image_1203ik" not in body, (
        "a stale image is being exonerated like an unreachable app — a failure judged on "
        "the old handler may still exist in the new source")


def test_the_gate_keeps_its_own_copy_of_this_fact():
    """★ SCOPE. The delivery gate said this first, and #1203ik is the SECOND exit.

    `_build_currency_caveat_1202vn` appends the same fact to the `business_chain_failing`
    blocker, for the identical reason ("tiktok-r136 ... the warning fired 36 times into the
    log while 43 gate snapshots carried a `business_chain_failing` detail and NOT ONE of them
    mentioned it"). I overestimated #1203ik before reading that — the lane reading a
    remediation task was not in the dark.

    Pinned so the overlap stays visible: if #1202vn's copy is ever removed, this reddens and
    whoever removed it learns that #1203ik does NOT cover the blocker path.
    """
    import pathlib
    dg = pathlib.Path(
        _AGENT, "env_generator/llm_generator/multi_agent/runtime/delivery_gate.py"
    ).read_text(encoding="utf-8")
    assert "def _build_currency_caveat_1202vn" in dg, (
        "#1202vn's caveat is gone — #1203ik only covers the validation report, NOT the "
        "delivery-gate blocker the lane's remediation is built from")
    # Pinned on the CALL via AST, not a substring: `def
    # _build_currency_caveat_1202vn(authored) -> str:` contains the same text, so deleting
    # the call left this green as a mutation — the assertion was reading the definition.
    import ast
    tree = ast.parse(dg)
    called = [n for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
              and n.func.id == "_build_currency_caveat_1202vn"]
    assert called, (
        "the caveat is defined but never CALLED, so the business_chain blocker no longer "
        "carries it — #1203ik only covers the validation report")
