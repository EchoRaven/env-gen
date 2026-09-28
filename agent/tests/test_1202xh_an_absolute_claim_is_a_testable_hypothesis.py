"""#1202xh: two docstrings asserted things the corpus falsifies. Both now say what is true.

Swept the 283 absolute claims ("EVERY", "NEVER", "cannot", "by construction") in runtime
docstrings and checked the ones that make a claim about a set the corpus can enumerate. Two
were wrong. Neither mechanism was broken -- both claims were the RATIONALE beside working
code, which is the more dangerous kind, because the next reader stops checking there.

1. `registryhub._tag_parked_probe_1202dw` said a parked `__`-probe "can never reach
   `implemented`". MEASURED: 95 parked-probe registrations across 61 runs, and 42 carry
   `status=implemented` -- most recently r135's `/__noop_orchestrator_read_probe__`. The
   delivered r135 then SERVES it (200) and it is one of the 31 paths in the app's public
   `openapi.json`, so opening `/docs` shows a framework probe among the app's endpoints;
   4 of 176 delivered backends carry one. The TAGGING works -- every parked probe from r123
   onward is tagged `infra` -- so the exemption does the work, not the claim.

2. `backend_audit._declared_public_materials_1202gt` said it and `#1202gd` "cannot disagree",
   both reading the same file and key. They can: `#1202gd` matches the entity name
   case-SENSITIVELY (`== table`) while this one lowercases both sides. MEASURED unreachable --
   0 of 1,706 entity names across 165 reference specs and 0 of 2,084 table names is anything
   but lower-case -- so the code is untouched and only the claim is corrected.

The rule this applies is already in the repo's own record: an absolute claim in a comment is a
falsifiable hypothesis, and the cheap ones are worth falsifying.
"""
import ast
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

_RT = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent", "runtime")


def _doc(module, func):
    with open(os.path.join(_RT, module), encoding="utf-8") as fh:      # #1202eu
        tree = ast.parse(fh.read())
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func),
              None)
    assert fn is not None, "%s.%s is gone" % (module, func)
    return ast.get_docstring(fn) or ""


def test_the_parked_probe_claim_is_quoted_and_falsified_not_merely_deleted():
    """The old wording SHOULD still appear -- quoted, beside the number that kills it.

    Deleting a wrong claim loses the record of what was believed; the first draft of this
    test asserted the phrase was absent and failed on the correction itself.
    """
    doc = _doc("registryhub.py", "_tag_parked_probe_1202dw")
    assert "can never reach" in doc, "the claim being corrected is no longer quoted"
    assert "THE CORPUS SAYS OTHERWISE" in doc.upper(), (
        "the claim is stated without the falsification beside it")
    assert "42" in doc and "95" in doc, (
        "the correction dropped the measurement that falsifies it")
    assert "openapi" in doc.lower(), (
        "the consequence -- the probe ships in the app's public surface -- is unstated")


def test_the_parked_probe_tagging_itself_is_untouched():
    """★ The mechanism was never the problem -- a correction to prose must not cost it."""
    with open(os.path.join(_RT, "registryhub.py"), encoding="utf-8") as fh:   # #1202eu
        src = fh.read()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "_tag_parked_probe_1202dw")
    body = ast.unparse(fn)
    assert "infra" in body, "the tag the exemption depends on is gone"


def test_the_two_visibility_readers_no_longer_claim_they_cannot_disagree():
    doc = _doc("backend_audit.py", "_declared_public_materials_1202gt")
    assert "so the two cannot disagree" not in doc, "the falsified claim is back"
    assert "case-SENSITIVELY" in doc or "case-sensitively" in doc.lower(), (
        "the correction does not say HOW they can disagree")


def test_the_case_sensitivity_difference_is_still_real():
    """★ Pins the fact the corrected docstring now states, so it cannot rot into a lie again.

    If both matchers are ever made consistent this fails, and the docstring should go back to
    claiming they agree -- which is the right outcome, reached deliberately."""
    with open(os.path.join(_RT, "backend_audit.py"), encoding="utf-8") as fh:  # #1202eu
        src = fh.read()
    tree = ast.parse(src)
    gd = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "_declared_public_1202gd")
    gt = next(n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "_declared_public_materials_1202gt")
    gd_src, gt_src = ast.unparse(gd), ast.unparse(gt)
    assert ".lower() == want" in gt_src, gt_src[-400:]
    assert ".lower() == table" not in gd_src, (
        "#1202gd now lowercases too; the docstrings should be updated to say they agree")
