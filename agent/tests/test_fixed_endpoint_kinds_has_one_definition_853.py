r"""#853: `FIXED_ENDPOINT_KINDS` had SIX definitions, and five of them were the same strict subset.

`kickoff.contract.control_surface_kind_for_path` asserts in its docstring:

    ``"control"`` is a member of :data:`FIXED_ENDPOINT_KINDS`, so every gate that points there
    skips it.

`chain_executor` did **not** point there. It carried its own
`_FIXED_ENDPOINT_KINDS = {"auth", "oauth", "infra", "spine"}` — missing `control`, `control_plane`
and `health` — and used it to decide which endpoints get a synthetic business-create chain step.

So a `POST /api/<col>` tagged `control` fell through the skip and got a step with a generated body
expecting 200/201. A control-plane POST answers that with a 400, and `chain_executor`'s own
comments record where that goes: *"business_chain fails forever -> the milestone can never
deliver"*.

**Zero live exposure**, measured before changing anything: the 6 control-surface endpoints the
framework registers (`/health`, `/api/v1/reset`, `/api/v1/tenants` x3, `/api/v1/admin/init-tenant`
— 864 records across 144 runs) all carry `kind=infra`, which BOTH sets contain. The `control` tag
is a fallback for a **lane-drafted** control path, and no lane drafted one in 151 Netflix runs.
The change is therefore provably behaviour-identical on the whole corpus and matters only for the
apps the framework exists to generalise to — a CMS or dashboard clone whose lane does draft one.

The same literal, `{"auth", "oauth", "infra", "spine"}`, was hand-listed in **six** modules —
`chain_executor`, `database_scaffold`, `mcp_scaffold`, `lifecycle`, `kickoff/cross_check_suite`
and (as a variant) `delivery_gate` — and **all six omitted the same three kinds**. Each site's own
comment names the whole surface: *"the orchestrator-registered fixed surface"*, *"the runtime-owned
FIXED surface"*. The names differed (`_NON_BUSINESS_KINDS`, `_MISSING_TABLE_FIXED_KINDS`,
`_FIXED_KINDS`), which is why a grep for the constant found one and a grep for the LITERAL found
six.

`delivery_gate`'s is a deliberate variant (it adds `custom`), so it is composed from the canonical
set rather than replaced. Its own omission is the sharpest illustration: it listed `control_plane`
and not `control` — exempting the spelling that never occurs and missing the one
`control_surface_kind_for_path` actually emits.

`mcp_scaffold`'s consequence is the most concrete: a `control` endpoint would be projected as an
**MCP tool**, handing an agent `reset` or `init-tenant`.

★ The test that matters is not "the copies agree". It is **"there is no second copy"** — agreement
can be restored by hand and diverge again, which is exactly what six modules did.

★ And a reading lesson: the first run of the scanner reported three offenders and I read that as
the complete list. It was **pytest eliding a long assertion repr** (`'delivery_gate.py:1395 _...'`).
Two more were in the same output, behind the ellipsis. Re-run to a clean scan; do not count
offenders off a truncated failure message.
"""
import pathlib
import re

import pytest

from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce
from env_generator.llm_generator.multi_agent.runtime.kickoff import contract as ct


_RUNTIME = pathlib.Path(ce.__file__).resolve().parent


def test_the_canonical_set_is_populated():
    """Non-vacuity: an empty or renamed constant makes everything below vacuous."""
    assert {"auth", "oauth", "infra", "spine", "control"} <= set(ct.FIXED_ENDPOINT_KINDS)


def test_the_chain_author_uses_the_canonical_set():
    """Resolved lazily — three tests exec this module's source into a synthetic package and
    hand-stub its module-level relative imports, so a new one there fails as
    `ModuleNotFoundError: No module named 'ce_pkg.kickoff'`. The behavioural cases below are what
    actually prove the wiring; this one just pins the accessor."""
    assert set(ce._fixed_endpoint_kinds_853()) == set(ct.FIXED_ENDPOINT_KINDS)


def test_the_isolated_exec_harnesses_still_load_this_module():
    """★ Non-obvious constraint, now a test. `chain_executor.py` may not grow a module-level
    relative import beyond the ones those harnesses stub; the failure is a collection error whose
    message names neither the file nor the rule."""
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-m", "pytest", "-q",
                        "tests/test_chain_string_keys.py",
                        "tests/test_chain_notnull_recovery.py",
                        "tests/test_chain_control_plane_probe.py"],
                       cwd=pathlib.Path(__file__).resolve().parents[1],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:]


def test_no_module_defines_a_second_copy():
    """★ The real invariant. A literal listing the fixed kinds anywhere but `contract.py` is a
    copy waiting to diverge — this one sat one word short for long enough that a docstring in
    another file grew a claim about it."""
    pat = re.compile(r'\{\s*"(?:auth|oauth|infra|spine)"(?:\s*,\s*"[a-z_]+")+\s*,?\s*\}')
    offenders = []
    for f in sorted(_RUNTIME.rglob("*.py")):
        if f.name.startswith("test_"):
            continue
        for n, line in enumerate(f.read_text(errors="ignore").split("\n"), 1):
            if line.lstrip().startswith("#"):
                continue                        # a comment quoting the old literal is not a copy
            if pat.search(line) and f.name != "contract.py":
                offenders.append(f"{f.relative_to(_RUNTIME)}:{n} {line.strip()}")
    assert len(list(_RUNTIME.rglob("*.py"))) > 40, "non-vacuity: the scan must see the tree"
    assert not offenders, "a second definition of the fixed-kind set:\n" + "\n".join(offenders)


def test_the_scanner_would_catch_a_reintroduction():
    """Non-vacuity for the scanner: prove it matches the literal that was actually there."""
    pat = re.compile(r'\{\s*"(?:auth|oauth|infra|spine)"(?:\s*,\s*"[a-z_]+")+\s*,?\s*\}')
    assert pat.search('_FIXED_ENDPOINT_KINDS = {"auth", "oauth", "infra", "spine"}')


# --- behaviour ----------------------------------------------------------------------------------

def _endpoints(kind):
    return [{"id": "POST /api/widgets", "method": "POST", "path": "/api/widgets",
             "metadata": {"kind": kind}, "schema": {}},
            {"id": "GET /api/widgets", "method": "GET", "path": "/api/widgets",
             "metadata": {"kind": kind}, "schema": {}}]


def _actions(kind):
    """`synthesize_default_chain` returns a list of CHAINS, each with its own `steps` — the first
    version of this helper read `action` off the chain dict and got `['']`, which would have made
    every case below pass vacuously. Non-vacuity is asserted separately for exactly that reason."""
    out = ce.synthesize_default_chain(_endpoints(kind)) or []
    acts = []
    for chain in out:
        if not isinstance(chain, dict):
            continue
        for st in chain.get("steps") or []:
            if isinstance(st, dict):
                acts.append(str(st.get("action", "")))
    return acts


def test_a_business_collection_still_gets_its_create_step():
    """Non-vacuity for the behavioural half: the skip must not swallow real business endpoints."""
    assert any("create /api/widgets" in a for a in _actions("business")), _actions("business")


@pytest.mark.parametrize("kind", ["control", "control_plane", "health"])
def test_a_control_surface_post_is_not_given_a_business_create_step(kind):
    """The three kinds the local copy was missing. A generated body against a control-plane POST
    is a 400, and a 400 in business_chain wedges the milestone permanently."""
    assert not any("create /api/widgets" in a for a in _actions(kind)), (kind, _actions(kind))


@pytest.mark.parametrize("kind", ["auth", "oauth", "infra", "spine"])
def test_the_kinds_that_already_worked_still_work(kind):
    """Non-regression: the four the local copy did have. `infra` is the one that matters — it is
    what all 864 real control-surface records carry, so this pins the corpus outcome unchanged."""
    assert not any("create /api/widgets" in a for a in _actions(kind)), (kind, _actions(kind))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
