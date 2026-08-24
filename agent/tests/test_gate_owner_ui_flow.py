"""FIX #176 — deliverability_ui_flow_missing was a genuinely UNOWNED gate token (absent from
_GATE_OWNER, _COVERED_ELSEWHERE, and every bespoke helper) → the delivery-gate decline logged
"NO remediation owner" and relied on incidental clearing (it blocked gmrun12 M2). Route it to
the VERIFIER (run+record the flow validation — non-destructive, mirrors
verification_checklist_not_ready). deliverability_dead_artifacts is INTENTIONALLY left unowned:
its "wire-or-remove" remediation is destructive (a lane told to delete a "dead" endpoint could
remove one that's actually needed) and needs a bespoke design, not a blind owner. LOCAL-ONLY.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _gate_owner_map():
    from multi_agent.runtime import remediation_dispatcher as rd
    tree = ast.parse(Path(rd.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict) and any(
                isinstance(t, ast.Name) and t.id == "_GATE_OWNER" for t in node.targets):
            out = {}
            for k, v in zip(node.value.keys, node.value.values):
                if (isinstance(k, ast.Constant) and isinstance(v, ast.Tuple) and v.elts
                        and isinstance(v.elts[0], ast.Constant)):
                    out[k.value] = v.elts[0].value
            return out
    return {}


def test_ui_flow_missing_routed_to_verifier():
    # closes the confirmed NO-remediation-owner gap (non-destructive run+record)
    assert _gate_owner_map().get("deliverability_ui_flow_missing") == "verifier"


def test_dead_artifacts_owner_is_non_destructive():
    """The guard did its job; #1042 is the bespoke design it was asking for.

    This used to assert the token had NO owner, because "a naive owner here would
    be DESTRUCTIVE (delete a falsely-'dead' artifact) — this guard flags any
    future blind assignment for a deliberate bespoke-design review instead". #1042
    is that review: it routes by KIND (endpoints/tables/mcp_tools to backend, and
    `files`/`pages_without_files` to frontend via bug_create rather than deleting
    their declarations) and tells the owner to WIRE or DEPRECATE, never delete.

    So the property to pin is not absence — it is that the remediation stays
    non-destructive. An owner who is told to delete is the failure this guards.
    """
    from multi_agent.runtime import remediation_dispatcher as rd
    assert _gate_owner_map().get("deliverability_dead_artifacts") == "backend"
    src = Path(rd.__file__).read_text(encoding="utf-8")
    i = src.index('"deliverability_dead_artifacts": (')
    _end = src.find('"deliverability_missing_seed"', i)
    guidance = src[i:_end if _end != -1 else len(src)]
    assert "deprecate" in guidance.lower()
    assert "rather than deleting" in guidance
    for destructive in ("delete the", "remove the file", "rm "):
        assert destructive not in guidance.lower(), destructive
