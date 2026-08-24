"""FIX #134 — projected owner comparisons coerce the caller id to the OWNER COLUMN's type.

instagram run-57, live: the lane declared messages.sender_id as TEXT while _fw_uid
int-coerces a digit JWT sub (the run-39 fix for INTEGER owner columns) -> postgres
`operator does not exist: text = integer` -> GET /api/messages 500 -> STUCK-abort.
The Python-level ownership gate had the same poison: "16" != 16 denies every owner.
_fw_owner_val(cls, col, user) looks at the ORM column's python_type and coerces to match.

ENV-AGNOSTIC + LOCAL-ONLY (agent/tests/ gitignored).
"""

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_skeleton import _DATABASE_PY  # noqa: F401,E402 (import sanity)


def _exec_helper():
    """Exec the generated main-template helpers (_fw_uid + _fw_owner_val) standalone."""
    from multi_agent.runtime import backend_skeleton as bs
    import re
    src = Path(bs.__file__).read_text()
    # pull the two helper defs out of the rendered skeleton template string
    # Start at _fw_dbg, not _fw_uid. The helpers call _fw_dbg from every except
    # handler, so slicing it off turned each CAUGHT error into an uncaught
    # NameError from inside the handler — the AttributeError on a stub column
    # that _fw_owner_val is documented to swallow ("every failure ... falls back
    # to the user id, completely unaffected") became a hard failure instead.
    m = re.search(r'def _fw_dbg\(where, exc=None\):.*?(?=\nBase\.metadata)', src, re.DOTALL)
    assert m, "helpers not found in backend_skeleton template"
    # _fw_dbg reads the template's module-level debug flag, which lives further
    # up than any sane slice; off is the production default.
    ns: dict = {"_FW_DEBUG": False}
    exec(compile(m.group(0), "helpers.py", "exec"), ns)
    return ns["_fw_uid"], ns["_fw_owner_val"]


class _Col:
    def __init__(self, pt):
        self.type = types.SimpleNamespace(python_type=pt)


class _TextOwnerModel:
    sender_id = _Col(str)


class _IntOwnerModel:
    user_id = _Col(int)


def test_text_owner_column_gets_str_value():
    _fw_uid, _fw_owner_val = _exec_helper()
    # digit sub -> _fw_uid gives int 16; TEXT column must get "16"
    assert _fw_uid({"sub": "16"}) == 16
    assert _fw_owner_val(_TextOwnerModel, "sender_id", {"sub": "16"}) == "16"


def test_int_owner_column_keeps_int_value():
    _, _fw_owner_val = _exec_helper()
    assert _fw_owner_val(_IntOwnerModel, "user_id", {"sub": "16"}) == 16


def test_unknown_column_falls_back_to_fw_uid():
    _fw_uid, _fw_owner_val = _exec_helper()
    class NoCol: pass
    assert _fw_owner_val(NoCol, "owner_id", {"sub": "16"}) == _fw_uid({"sub": "16"})


def test_uuid_str_sub_untouched_on_text_column():
    _, _fw_owner_val = _exec_helper()
    u = "8f9aee44-959d-4e66-af7e-e404e188b9b2"
    assert _fw_owner_val(_TextOwnerModel, "sender_id", {"sub": u}) == u


def test_projector_emits_owner_val_not_bare_uid():
    from multi_agent.runtime import route_projector as rp
    src = Path(rp.__file__).read_text()
    import re
    # every EMITTED owner comparison goes through _fw_owner_val; bare _fw_uid(user)
    # may remain only in comments and the helper definitions themselves.
    emissions = [l for l in src.splitlines()
                 if "_fw_uid(user)" in l and ('f"' in l or "f'" in l)]
    assert not emissions, f"bare _fw_uid emissions remain: {emissions}"
    assert src.count("_fw_owner_val") >= 10


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
