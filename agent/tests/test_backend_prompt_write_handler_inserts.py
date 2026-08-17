"""#410 (business_chain-surfaced live on netflix r7): the backend prompt had NO rule on write-
handler INSERT completeness, so lane-authored create handlers (custom_routes.py POST /api/profiles
/my-list) either (a) inserted an EXPLICIT NULL for a DEFAULT-ed NOT-NULL column (created_at) —
bypassing the DB default -> NotNullViolation -> 400 (same class as #409, but in the create path
not the seed), or (b) omitted a REQUIRED FK (my_list.title_id) the verifier's chain never sent
because it wasn't declared in the endpoint request shape -> NotNullViolation -> 400 (+ trips the
contract-alignment gate). business_chain then failed on POST creates (r7 attempt 5/6). New bullet
6c teaches the lane: OMIT auto-defaulted/system columns (id/created_at/updated_at + any NOT-NULL
DEFAULT-ed col) so the DB fills them, and SUPPLY+DECLARE every required no-default column (parent
FKs) so the chain sends it. Generalizes to any app's create handlers. This locks the rule in.
"""
import pathlib

_PROMPT = pathlib.Path(__file__).resolve().parents[1] / (
    "env_generator/llm_generator/multi_agent/prompts/v3/backend_agent.j2")


def _src():
    return _PROMPT.read_text(encoding="utf-8")


def test_write_handler_block_present():
    assert "6c. WRITE HANDLERS" in _src()


def test_omit_autodefaulted_columns_rule():
    src = _src()
    assert "OMIT auto-defaulted / system columns" in src
    assert "BYPASSES the DEFAULT" in src           # names the exact failure mechanism
    assert "created_at" in src and "updated_at" in src


def test_supply_and_declare_required_columns_rule():
    src = _src()
    assert "SUPPLY every REQUIRED" in src
    assert "title_id" in src                        # the r7 required-FK evidence
    assert "the verifier's chain actually SENDS it" in src
    assert "contract-alignment gate" in src


def test_jinja_still_parses():
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(str(_PROMPT.parent)))
    env.parse(_src())


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
