"""#1202w5: #731 could never fire, so a silently-ignored schema declaration had no witness.

`_warn_unknown_schema_keys_731` says when a lane's schema carries sub-keys nothing in the
framework reads. Its only call site passed `getattr(self, "_logger", None)`, and `RegistryHub`
has no `_logger` — the name appears exactly once in that module, in that `getattr` — so the
argument was always None and the function's first guard returned immediately. It fired 0 times
across every run log in the corpus.

What it would have said, measured over the 4940 stored endpoint schemas: 189 unknown keys
across 23 runs. Most are harmless prose (`description` 45, `summary` 24, `notes` 18). About 34
are not: `path_params` 14, `response_shape` 10, `query_params` 3, `params` 3, `request_body` 2,
`body` 1 — a lane declaring the request/query/response shape under a name the framework does
not read, so the probe body, the chain synth and the frontend all get nothing. That is #730's
defect under a different spelling, and #730 was found and fixed; these were not, because
nothing said them.

Two halves, and either alone is useless: the warning has to be ABLE to fire, and its finding
has to survive the run (#947). The fold itself stays out of scope on #731's own division of
labour — "if the name is better than the one we read, the fold belongs in
_merge_query_alias_730" — and the artifact is what makes that a question the files can answer.
"""
import json
import logging
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime import registryhub as RH                # noqa: E402
from multi_agent.runtime.hub_registry import HubRegistry         # noqa: E402


def _hub(tmp_path):
    return HubRegistry(tmp_path).registryhub


def test_the_warning_fires_without_a_logger_being_handed_in(caplog):
    """The whole defect: `logger=None` used to mean silence. It now means "use mine"."""
    with caplog.at_level(logging.WARNING, logger=RH.__name__):
        RH._warn_unknown_schema_keys_731("POST", "/api/x", {"request_body": {}}, None)
    said = " ".join(r.getMessage() for r in caplog.records)
    assert "#731" in said and "request_body" in said


def test_a_schema_of_only_known_keys_stays_quiet(caplog):
    with caplog.at_level(logging.WARNING, logger=RH.__name__):
        RH._warn_unknown_schema_keys_731(
            "GET", "/api/x", {"request": {}, "response": {}, "query": {},
                              "headers": {}, "auth_required": False, "response_key": "items"},
            None)
    assert not [r for r in caplog.records if "#731" in r.getMessage()]


def test_an_underscore_key_is_framework_bookkeeping(caplog):
    with caplog.at_level(logging.WARNING, logger=RH.__name__):
        RH._warn_unknown_schema_keys_731("GET", "/api/x", {"_updated_at": 1}, None)
    assert not [r for r in caplog.records if "#731" in r.getMessage()]


def test_registering_through_the_hub_reaches_the_artifact(tmp_path):
    """End to end through the real `register_endpoint`, which is the only caller."""
    rh = _hub(tmp_path)
    rh.register_endpoint("POST", "/api/x", agent="backend", status="implemented",
                         schema={"request": {"a": 1}, "request_body": {"b": 2}})
    f = tmp_path / "logs" / "unknown_schema_keys_1202w5.jsonl"
    rec = json.loads(f.read_text().strip())
    assert rec["count"] == 1
    assert "request_body" in rec["endpoints"][0] and "POST /api/x" in rec["endpoints"][0]


def test_a_clean_registration_writes_no_artifact(tmp_path):
    rh = _hub(tmp_path)
    rh.register_endpoint("GET", "/api/y", agent="backend", status="implemented",
                         schema={"request": {}, "response": {}})
    assert not (tmp_path / "logs" / "unknown_schema_keys_1202w5.jsonl").exists()


def test_the_recorder_guards_like_its_siblings(tmp_path):
    assert not RH.record_unknown_schema_keys_1202w5(tmp_path, [])
    assert not RH.record_unknown_schema_keys_1202w5(None, ["x"])


def test_the_call_site_hands_over_what_the_artifact_needs():
    """AST (#943). The finding cannot be landed without the hub path, and the defect this
    fixes was precisely an argument that was always empty at the call site."""
    import ast
    import inspect

    src = inspect.getsource(RH)
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_warn_unknown_schema_keys_731"]
    assert len(calls) == 1, f"expected one call site, found {len(calls)}"
    args = [ast.unparse(a) for a in calls[0].args]
    assert "self.hub_dir" in args, f"the hub path must be passed, got {args}"


def test_the_function_no_longer_returns_on_a_missing_logger():
    """A regression guard on the exact shape of the dead mechanism."""
    import ast
    import inspect

    fn = next(n for n in ast.walk(ast.parse(inspect.getsource(RH)))
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
              and n.name == "_warn_unknown_schema_keys_731")
    body = ast.unparse(fn)
    assert "logger is None" in body, "the None case must still be handled"
    assert "getLogger" in body, "…by supplying a logger, not by returning"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
