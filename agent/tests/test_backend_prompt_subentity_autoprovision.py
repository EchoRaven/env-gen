"""#408 (FW_DEBUG+business_chain-surfaced on netflix r6): the v3 backend prompt taught only
SINGLE-level owner-scoping (`owner_scoped_reads` for tables a user owns directly) and was
SILENT on the TWO-level pattern (user -> profile/workspace/account -> per-sub-entity rows).
With no guidance, the lane hand-wrote a `_resolve_profile_id` that 404s 'no profile; create one
first' when the caller has none — and the verifier's business_chain registers a BRAND-NEW user
with no sub-entity row, so every per-sub-entity chain (GET /api/continue-watching, /api/my-list)
failed NON-IDEMPOTENTLY (passing only when a prior test left a row). The framework already
auto-provisions the owner on owner-scoped WRITES (#390-394); the fix teaches the lane to do the
same on the read/list path — auto-provision a default sub-entity on first access, NEVER 404 for a
merely-absent one. Generalizes to any user->sub-entity->resource app. This locks the guidance in.
"""
import pathlib

_PROMPT = pathlib.Path(__file__).resolve().parents[1] / (
    "env_generator/llm_generator/multi_agent/prompts/v3/backend_agent.j2")


def _src():
    return _PROMPT.read_text(encoding="utf-8")


def test_two_level_ownership_block_present():
    src = _src()
    assert "6b. PER-USER SUB-ENTITIES" in src
    assert "TWO-LEVEL OWNERSHIP" in src


def test_never_404_for_missing_subentity():
    # the exact failure mode (r6): a 'create one first' 404 for a fresh user
    src = _src()
    assert "NEVER 404 for a merely-absent sub-entity" in src
    assert "create one first" in src  # names the anti-pattern verbatim


def test_autoprovision_rule_present():
    src = _src()
    assert "AUTO-PROVISION a default sub-entity" in src
    # ties it to why: fresh business_chain user + consistency with framework write-path
    assert "freshly-registered user" in src
    assert "auto-provisions the owner on owner-scoped writes" in src


def test_insert_robustness_generalizes():
    # #408 refinement: #407 only auto-defaults timestamp/date/bool NOT-NULL cols,
    # NOT text/int — so the prompt must tell the lane to SUPPLY required domain
    # fields itself (else a sub-entity with a NOT-NULL text `name` breaks the
    # auto-provision insert in a DIFFERENT app). Generalization guard.
    src = _src()
    assert "SUPPLY the sub-entity's required domain fields yourself" in src
    assert "NOT-NULL text/number column has NO auto-default" in src
    assert "auto-defaults NOT-NULL timestamp/date/bool columns" in src


def test_jinja_still_parses():
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(str(_PROMPT.parent)))
    env.parse(_src())  # raises TemplateSyntaxError if the added literal broke the block


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
