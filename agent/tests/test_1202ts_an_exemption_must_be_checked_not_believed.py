r"""#1202ts: the framework-only exemption list asserted something nothing ever checked.

#1202cw's sweep is general -- it enumerates every runtime module holding a raw `write_text` and
demands each be guarded or exempt. The exemption list carries a PROSE reason per module ("audit
output", "writes reports, never app sources", "emits the framework's own skeleton files"), and
nothing ever compared that prose to `path_is_lane_owned_1202cw`, the predicate the choke point
itself uses. Three of the claims were false:

  frontend_audit.py    "audit output"                     -> rewrites lane pages/components
                                                              (fixed as #1202tr)
  deliverability.py    "writes reports, never app sources" -> restores app/backend/seed_data.json
  backend_skeleton.py  "emits the framework's own skeleton" -> #84 AMPLIFIES the lane's authored
                                                              seed and writes it back

So the writes that most deserved recording -- overwrites of the lane's own seed -- were the ones
the census could not see. `seed_data.json` is lane-owned by the same frozenset that makes
`custom_routes.py` lane-owned, and the realistic shape is not an empty file: a contract with
tables declared and zero rows is 33 bytes on disk, so `framework_write_1202cw` treats it as
occupied and REFUSES an undeclared overwrite. Both sites therefore declare their ticket (#1068
restores from the committed HEAD; #84 lifts a thin lane seed to the density floor), which keeps
behaviour identical and makes the write countable.

THE FIX THAT MATTERS is not the three modules -- it is this file's last test, which resolves
each exempted module's write target to a literal basename and asks the REAL predicate instead of
reading the prose. It catches deliverability.py and backend_skeleton.py on its own. It cannot
catch frontend_audit.py, whose target came from `rglob("*.jsx")` with no literal to resolve, and
that limit is stated here rather than left for the next person to discover: a claim-checker is a
floor, not a proof.

LOCAL-ONLY (gitignored)."""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM_DIR = ROOT / "env_generator" / "llm_generator"
for p in (str(ROOT), str(LLM_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from multi_agent.runtime.path_routed_workspace import (  # noqa: E402
    path_is_lane_owned_1202cw,
)

RUNTIME = LLM_DIR / "multi_agent" / "runtime"
RATCHET = ROOT / "tests" / "test_1202cw_clobbering_lane_work_is_a_declared_exception.py"


def _exemptions():
    body = RATCHET.read_text(encoding="utf-8").split(
        "_FRAMEWORK_ONLY_WRITERS_1202TD = {")[1].split("\n}")[0]
    return dict(re.findall(r'"([^"]+\.py)":\s*"([^"]*)"', body))


def _string_literals(node):
    return [n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _lane_owned_basename(lit: str) -> bool:
    base = lit.rsplit("/", 1)[-1]
    if not base:
        return False
    return (path_is_lane_owned_1202cw("/x/run/app/backend/" + base)
            or path_is_lane_owned_1202cw("/x/run/app/frontend/" + base))


def _resolved_write_targets(path: Path):
    """(lineno, literal) for each unmarked `write_text`, following one level of `name = expr`."""
    src = path.read_text(encoding="utf-8", errors="replace")
    lines = src.split("\n")
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    assigns = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 \
                and isinstance(n.targets[0], ast.Name):
            assigns.setdefault(n.targets[0].id, []).append(n.value)
    out = []
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "write_text"):
            continue
        if "# raw:" in lines[n.lineno - 1]:
            continue
        tgt = n.func.value
        lits = _string_literals(tgt)
        if isinstance(tgt, ast.Name):
            for v in assigns.get(tgt.id, []):
                lits += _string_literals(v)
        out += [(n.lineno, l) for l in lits]
    return out


def test_the_resolver_finds_targets_at_all():
    """Non-vacuity: a resolver that silently stopped working would report a clean tree."""
    seen = sum(len(_resolved_write_targets(RUNTIME / rel))
               for rel in _exemptions() if (RUNTIME / rel).is_file())
    assert seen >= 10, f"only {seen} write targets resolved — the AST walk has drifted"


def test_the_predicate_still_calls_the_seed_lane_owned():
    """The premise the check rests on. If this flips, the check below goes quietly blind."""
    assert path_is_lane_owned_1202cw("/x/run/app/backend/seed_data.json")
    assert path_is_lane_owned_1202cw("/x/run/app/backend/custom_routes.py")
    assert not path_is_lane_owned_1202cw("/x/run/app/backend/main.py")


def test_no_exemption_claims_framework_only_while_writing_a_lane_owned_name():
    """The rule: an exemption must be checked against the predicate, not believed."""
    liars = []
    for rel, reason in sorted(_exemptions().items()):
        f = RUNTIME / rel
        if not f.is_file():
            continue
        for lineno, lit in _resolved_write_targets(f):
            if _lane_owned_basename(lit):
                liars.append(f"{rel}:{lineno} writes {lit!r} but is exempt as {reason!r}")
    assert liars == [], (
        "these modules are exempt from #1202cw as framework-only writers, but their write "
        "target resolves to a LANE-OWNED name. Route the write through "
        "framework_write_1202cw (declaring clobber_ok when the overwrite is intended) and "
        "move the module into PROJECTORS: %s" % liars)


def test_the_seed_amplification_still_amplifies_and_is_now_counted():
    """Assert the CONSEQUENCE, not the call: #84 must still lift a thin seed to the density
    floor, and the overwrite must now appear in the census run_budget.json carries."""
    import json
    import tempfile
    from multi_agent.runtime.backend_skeleton import _ensure_seed_json
    from multi_agent.runtime.path_routed_workspace import lane_clobbers_1202cw

    be = Path(tempfile.mkdtemp()) / "app" / "backend"
    be.mkdir(parents=True)
    thin = {"users": [{"id": i, "email": f"u{i}@x.com", "name": f"U{i}"} for i in range(1, 4)]}
    (be / "seed_data.json").write_text(json.dumps(thin, indent=2), encoding="utf-8")

    _ensure_seed_json(be, amplify=True)

    rows = json.loads((be / "seed_data.json").read_text(encoding="utf-8"))["users"]
    assert len(rows) > len(thin["users"]), "#84's amplification stopped working"
    assert any(k.endswith("app/backend/seed_data.json")
               for k in lane_clobbers_1202cw()["declared"]), "the overwrite is still invisible"


def test_creating_an_absent_seed_is_not_counted_as_a_clobber():
    """The discriminator. Only the OVERWRITE is a clobber; creating the file where the lane
    never wrote one must not inflate the census -- a count that includes first-writes cannot
    answer the question #1011 asked."""
    import tempfile
    from multi_agent.runtime.backend_skeleton import _ensure_seed_json
    from multi_agent.runtime.path_routed_workspace import lane_clobbers_1202cw

    before = sum(lane_clobbers_1202cw()["declared"].values())
    be = Path(tempfile.mkdtemp()) / "app" / "backend"
    be.mkdir(parents=True)
    _ensure_seed_json(be)                       # no file yet -> creates
    assert (be / "seed_data.json").read_text(encoding="utf-8").strip() == "{}"
    assert sum(lane_clobbers_1202cw()["declared"].values()) == before
