"""#1202fv -- the two validation-record normalizers must not drift apart again.

There are two copies: HubRegistry.get_validation_results and the orchestrator's own
_get_validation_results. They already drifted once — #1032's comment in orchestrator.py
says so outright ("the OTHER half of #236 this copy was missing") — and different consumers
are fed by different copies:

    flow_coverage / deliverability / story_hub  <- HubRegistry's
    delivery_gate                              <- the orchestrator's

#1202fu is what a mismatch costs: a field the consumer read did not exist on the record its
producer emits, so #757's latest-wins silently picked an arbitrary record for the life of
the gate. An audit at that time found no OTHER live mismatch — the three HubRegistry-fed
consumers read only {metadata, name, recorded_at, status}, which both copies emit — so this
test exists to keep it that way rather than to fix something.

It asserts the CORE contract (the keys consumers actually read), not key-set equality: the
copies legitimately carry extra fields for their own callers (pr_id on one side; evidence /
artifacts / duration_seconds on the other).
"""
import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
MA = REPO / "multi_agent"

# The keys every consumer of a validation record relies on, whichever copy produced it.
CORE = {"name", "status", "metadata", "recorded_at"}


def _dict_keys_in(path: Path, *, func: str = None, near: str = None) -> set:
    """String keys of every dict literal inside `func`, or within the block that follows
    the landmark `near`. Landmark-anchored, never a fixed byte window (#943)."""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    out = set()
    if func:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == func:
                for n in ast.walk(node):
                    if isinstance(n, ast.Dict):
                        for k in n.keys:
                            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                                out.add(k.value)
        return out
    idx = src.index(near)
    lineno = src[:idx].count("\n") + 1
    for n in ast.walk(tree):
        if isinstance(n, ast.Dict) and lineno - 12 <= n.lineno <= lineno + 12:
            for k in n.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    out.add(k.value)
    return out


def test_hub_registry_copy_emits_the_core_contract():
    keys = _dict_keys_in(MA / "runtime" / "hub_registry.py",
                         func="get_validation_results")
    assert CORE <= keys, f"HubRegistry's normalizer dropped {sorted(CORE - keys)}"


def test_orchestrator_copy_emits_the_core_contract():
    keys = _dict_keys_in(MA / "orchestrator.py",
                         near='"recorded_at": c.get("updated_at", 0),')
    assert CORE <= keys, f"the orchestrator's normalizer dropped {sorted(CORE - keys)}"


def test_the_timestamp_is_renamed_by_both_and_read_under_the_new_name():
    """#1202fu in one assertion: both copies RENAME updated_at -> recorded_at, so any
    consumer that reads recency must read `recorded_at`."""
    for path, kw in ((MA / "runtime" / "hub_registry.py", {"func": "get_validation_results"}),
                     (MA / "orchestrator.py",
                      {"near": '"recorded_at": c.get("updated_at", 0),'})):
        assert "recorded_at" in _dict_keys_in(path, **kw), f"{path.name} stopped emitting it"

    sys.path.insert(0, str(REPO))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from multi_agent.runtime.delivery_gate import _ts757
    assert _ts757({"recorded_at": 42.0}) == 42.0, (
        "the gate's recency reader does not read the field the producers emit")
