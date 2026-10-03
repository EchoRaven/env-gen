r"""#1203c4: #1203c2 was wired and never fired — it passed the TOOL where the resolver wants the HUB.

`_project_dir_1202q(hub_registry)` is `getattr(hub_registry, "base_dir", None)`. This module's two
older call sites pass `self.hub_registry`; #1203c2's new one passed `self`, a tool with no
`base_dir`, so the resolver returned None and `_unmapped_dataset_text_1203c2` read nothing.

CAUGHT ON r146, which carries #1203c2: `seed_audit_check` ran 19 times and the agent log records
each result in full — `{'flagged_tables': [], 'is_clean': True, 'examined': 2, 'candidates': 6,
'measured': True}` — with no `dataset_text_without_column_1203c2` key, while the helper called
with that run's directory returns `{'comments': ['text']}`.

★ #1203c2's OWN TESTS PASSED because every behavioural case monkeypatched `_project_dir_1202q`
to return the fixture path, so none of them ever exercised the argument the real tool passes.
The cases below are the ones that would have caught it: the ARGUMENT at the call site, read with
AST, and a run through the tool with a real hub-like object instead of a patched resolver.
"""
import asyncio
import json
import os
import sys
import types

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import tools.seed_tools as ST  # noqa: E402

_KEY = "dataset_text_without_column_1203c2"


def test_the_call_site_passes_the_hub_not_the_tool():
    """★ The defect, pinned where it lived. Read as the ARGUMENT rather than by behaviour,
    because behaviour was exactly what the monkeypatched tests could not see."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(ST))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "_unmapped_dataset_text_1203c2"]
    assert len(calls) == 1, "called %d time(s)" % len(calls)
    arg = calls[0].args[0]
    assert isinstance(arg, ast.Call), ast.dump(arg)[:140]
    assert getattr(arg.func, "id", "") == "_project_dir_1202q", ast.dump(arg)[:140]
    inner = arg.args[0]
    assert isinstance(inner, ast.Attribute) and inner.attr == "hub_registry", (
        "the resolver is given %s; it reads `base_dir`, which a tool does not have"
        % ast.dump(inner)[:120])


def test_every_resolver_call_in_this_module_agrees():
    """★ The convention is the evidence: three call sites, one argument shape. A fourth that
    differs is how this defect got in."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(ST))
    args = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_project_dir_1202q":
            a = n.args[0] if n.args else None
            args.append(getattr(a, "attr", None) or getattr(a, "id", None))
    assert len(args) >= 3, args
    assert set(args) == {"hub_registry"}, args


def test_it_fires_through_the_tool_with_a_real_hub(tmp_path, monkeypatch):
    """★ No patched resolver. A hub-like object carrying `base_dir` is all the real tool has, so
    that is what the test gives it."""
    from multi_agent.runtime.seed_audit import SeedReport
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (be / "seed_dataset.json").write_text(
        json.dumps({"videos": [{"id": 1, "caption": "#KEEPSWIMMING with BTS."}]}),
        encoding="utf-8")
    (be / "models.py").write_text(
        "class Video(Base):\n"
        "    __tablename__ = 'videos'\n"
        "    id = Column(Integer, primary_key=True)\n"
        "    title = Column(String)\n", encoding="utf-8")
    monkeypatch.setattr(ST, "audit_seed_data",
                        lambda *a, **k: SeedReport(flagged_tables=[], examined=2, candidates=2))
    hub = types.SimpleNamespace(base_dir=str(tmp_path))
    res = asyncio.run(ST.SeedAuditCheckTool(hub_registry=hub).execute())
    d = res.data if hasattr(res, "data") else res["data"]
    assert _KEY in d, sorted(d)
    assert d[_KEY]["unmapped"] == {"videos": ["caption"]}


def test_a_hub_without_a_base_dir_is_silent(tmp_path, monkeypatch):
    """The resolver legitimately returns None when the hub has no root — then there is nothing
    to read and nothing to claim, which is the pre-#1203c2 behaviour."""
    from multi_agent.runtime.seed_audit import SeedReport
    monkeypatch.setattr(ST, "audit_seed_data",
                        lambda *a, **k: SeedReport(flagged_tables=[], examined=2, candidates=2))
    res = asyncio.run(ST.SeedAuditCheckTool(
        hub_registry=types.SimpleNamespace()).execute())
    d = res.data if hasattr(res, "data") else res["data"]
    assert _KEY not in d, d
