r"""#731: `schema` is the one free-form field, which is why synonyms accumulate only there.

#730 recovered `schema.query` after it sat unread for a run. Sweeping for the same shape found
`schema.headers` (deliberately not folded — item 51: a header selects an actor) and then found
the mechanism:

    register_endpoint's PARAMETERS declare
        method / path / provider / status   named, typed
        schema                              {"type": "object"} — no properties, no required

Every sibling's name is pinned by the tool layer. `schema`'s sub-keys are not. A sweep of
`registryhub_tables`, `registryhub_ui_pages` and `registryhub_consumers` found ZERO
declared-but-unread fields, which is not luck: their names cannot drift. Only `schema` can.

So this warns rather than rejects. The lane's inventions have been reasonable — `query` describes
query parameters better than `request` does — and refusing an unknown sub-key would discard good
information to enforce a vocabulary. Making it visible is what #730 needed in order to be noticed
at all, and costs one line.

The known set is not a guess: it is exactly the six sub-keys that appear across r146, r147 and
r148, so all three runs produce zero warnings. The signal is reserved for the NEXT synonym.
"""
import json
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.registryhub import (
    _warn_unknown_schema_keys_731 as warn,
    _KNOWN_SCHEMA_KEYS_731 as KNOWN,
)


class _Log:
    def __init__(self):
        self.lines = []

    def warning(self, fmt, *a):
        self.lines.append(fmt % a)


# --- it names what nothing reads ---------------------------------------------------------------

def test_an_unknown_sub_key_is_named():
    lg = _Log()
    warn("GET", "/api/x", {"filters": {"a": 1}}, lg)
    assert lg.lines and "filters" in lg.lines[0]


def test_several_are_listed_in_order():
    lg = _Log()
    warn("GET", "/api/x", {"sort_by": 1, "filters": 2}, lg)
    assert "filters, sort_by" in lg.lines[0]


def test_the_endpoint_is_identified():
    lg = _Log()
    warn("get", "/api/titles", {"zzz": 1}, lg)
    assert "GET /api/titles" in lg.lines[0]


def test_it_says_the_information_is_kept():
    lg = _Log()
    warn("GET", "/api/x", {"zzz": 1}, lg)
    assert "KEPT, not dropped" in lg.lines[0]


def test_it_points_at_where_a_fold_would_go():
    lg = _Log()
    warn("GET", "/api/x", {"zzz": 1}, lg)
    assert "_merge_query_alias_730" in lg.lines[0]


# --- it stays quiet otherwise ----------------------------------------------------------------------

def test_known_keys_are_silent():
    lg = _Log()
    warn("GET", "/api/x", {k: {} for k in KNOWN}, lg)
    assert lg.lines == []


def test_underscore_keys_are_ignored():
    lg = _Log()
    warn("GET", "/api/x", {"_internal": 1}, lg)
    assert lg.lines == []


@pytest.mark.parametrize("schema", [None, "junk", 42, [], {}])
def test_degenerate_schema_is_silent(schema):
    lg = _Log()
    warn("GET", "/api/x", schema, lg)
    assert lg.lines == []


def test_no_logger_is_safe():
    warn("GET", "/api/x", {"zzz": 1}, None)


def test_a_broken_logger_cannot_break_registration():
    class _Bad:
        def warning(self, *a):
            raise RuntimeError("boom")
    warn("GET", "/api/x", {"zzz": 1}, _Bad())


# --- the known set matches reality, and the runs are quiet -------------------------------------------

def test_the_known_set_is_exactly_what_the_runs_use():
    """Not a guess: the six sub-keys that appear across r146/r147/r148."""
    seen = set()
    for run in ("netflix-web-r146", "netflix-web-r147", "netflix-web-r148"):
        h = Path(__file__).resolve().parents[1] / "generated" / run / "shared" / "hubs"
        if not h.is_dir():
            pytest.skip(f"{run} not on disk")
        d = json.loads((h / "registryhub_endpoints.json").read_text())
        for k, v in d.items():
            if not k.startswith("_") and isinstance(v, dict):
                seen |= set((v.get("schema") or {}).keys())
    assert seen == set(KNOWN), f"runs use {sorted(seen)}, known set is {sorted(KNOWN)}"


@pytest.mark.parametrize("run", ["netflix-web-r146", "netflix-web-r147", "netflix-web-r148"])
def test_no_historical_run_would_warn(run):
    """A new signal that fires on old data is noise on arrival."""
    h = Path(__file__).resolve().parents[1] / "generated" / run / "shared" / "hubs"
    if not h.is_dir():
        pytest.skip(f"{run} not on disk")
    d = json.loads((h / "registryhub_endpoints.json").read_text())
    lg = _Log()
    for k, v in d.items():
        if not k.startswith("_") and isinstance(v, dict):
            warn(v.get("method"), v.get("path"), v.get("schema"), lg)
    assert lg.lines == []


# --- wired, and after the record exists ---------------------------------------------------------------

def test_register_endpoint_calls_it():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import registryhub as rh
    src = inspect.getsource(rh.RegistryHub.register_endpoint)
    assert "_warn_unknown_schema_keys_731(" in src


def test_it_runs_after_the_record_is_built():
    """A logging fault must never lose a registration."""
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import registryhub as rh
    src = inspect.getsource(rh.RegistryHub.register_endpoint)
    assert src.index('"_updated_at": now') < src.index("_warn_unknown_schema_keys_731(")


# --- provenance -------------------------------------------------------------------------------------

def test_the_mechanism_is_recorded():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import registryhub as rh
    src = inspect.getsource(rh)
    i = src.index("#731: the sub-keys anything in the framework actually reads")
    block = " ".join(src[i:src.index("_KNOWN_SCHEMA_KEYS_731", i)].replace("#", " ").split())
    assert "no `properties`, no `required`" in block
    assert "zero declared-but-unread fields" in block


def test_why_it_warns_instead_of_rejecting():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import registryhub as rh
    src = inspect.getsource(rh)
    i = src.index("#731: the sub-keys anything in the framework actually reads")
    block = " ".join(src[i:src.index("_KNOWN_SCHEMA_KEYS_731", i)].replace("#", " ").split())
    assert "WARN, never reject" in block
    assert "discard good information to enforce a vocabulary" in block


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
