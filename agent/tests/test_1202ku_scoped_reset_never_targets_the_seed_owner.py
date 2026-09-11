"""#1202ku: a "scoped" control-plane reset must never be scoped to the seed-owning tenant.

`_scoped_reset_header` exists so a chain's `POST /api/v1/reset` deletes THAT chain's rows
instead of factory-wiping the shared fixture. Its docstring already named the thing to
protect -- "the DEFAULT tenant that OWNS the seed fixture" -- but guarded only ONE way in:
it refused to HARVEST the scope from `GET /api/v1/tenants`. The other side stayed open.

A chain registers through `/auth/register`, which mints its user in `default` (the schema's
`tenant_id TEXT NOT NULL DEFAULT 'default'`). So `last_reg_creds["tenant_id"]` -- preference
candidate 2, and often candidate 1 -- IS the seed owner in the ordinary case. Measured in the
corpus: 45 resets across 26 runs (netflix-local + tiktok-web, r96..r117) went out scoped to
`default`, the single largest scope target.

That is not a near-miss. The reset handler resolves the named tenant to its user ids and
deletes every business row owned by any of them; every seeded user belongs to `default`, so
the "scoped" reset removes the entire fixture. tiktok-r115 is the worked example: three
default-scoped resets, then `read_seed_video_comments` requesting video 1 and getting 404
-- while the framework's own note still read "TABLE `videos` HAS 39 LIVE ROW(S) (a seeded
id is 1)", the seed ledger describing rows that had just been deleted.

WHAT IS VERIFIED: the seed owner is refused from BOTH preference candidates, case-insensitively;
a legitimate own-tenant is still preferred; candidate 2 is still used when only candidate 1 is
the seed owner; the fallback is the zero-blast-radius synthetic scope; and the constant still
matches the schema literal it is derived from.

WHAT IS NOT: that redirecting the scope changes any chain's verdict on its own. It is safe
rather than free -- 0 of the corpus's 224 reset-bearing chains assert emptiness after a reset,
so nothing depended on the deletion happening.
"""
import ast
import pathlib
import sys

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from env_generator.llm_generator.multi_agent.runtime import chain_executor as ce  # noqa: E402

_HDR = "X-Tenant-Id"


def _scope(chain="c", own=None, reg=None):
    return ce._scoped_reset_header(chain, own, reg)[_HDR]


def test_seed_owner_refused_as_own_tenant():
    """★ The case: candidate 1 is the seed owner -> never sent."""
    assert _scope(own="default") .startswith("_fwscope_")


def test_seed_owner_refused_as_registered_tenant():
    """★ The ordinary case: /auth/register put the chain user in `default`."""
    assert _scope(reg={"tenant_id": "default"}).startswith("_fwscope_")


def test_seed_owner_refused_case_insensitively():
    for v in ("DEFAULT", "Default", "  default  "):
        assert _scope(own=v).startswith("_fwscope_"), v


def test_a_real_own_tenant_is_still_preferred():
    """The guard must narrow, not disable: a chain-created tenant is its own to reset."""
    assert _scope(own="chain-tenant-77") == "chain-tenant-77"
    assert _scope(reg={"tenant_id": "t-9"}) == "t-9"
    assert _scope(own="t-own", reg={"tenant_id": "t-reg"}) == "t-own"


def test_falls_through_to_candidate_two_not_straight_to_synthetic():
    """Only the seed-owning candidate is skipped -- the next one still gets its turn."""
    assert _scope(own="default", reg={"tenant_id": "mine-1"}) == "mine-1"


def test_synthetic_scope_is_deterministic_and_names_the_chain():
    a = _scope(chain="fyp_feed_comments_panel_flow", own="default")
    b = _scope(chain="fyp_feed_comments_panel_flow", own="default")
    assert a == b and "fyp_feed_comments_panel_flow" in a


def test_constant_matches_the_schema_literal_it_is_derived_from():
    """Ties the constant to its source of truth so the two cannot drift apart."""
    scaffold = (_AGENT / "env_generator/llm_generator/multi_agent/runtime"
                / "database_scaffold.py").read_text(encoding="utf-8")
    for name in ce._SEED_OWNER_TENANTS_1202KU:
        assert f"DEFAULT '{name}'" in scaffold, name
        assert f"INSERT INTO tenants (id, name) VALUES ('{name}'" in scaffold, name


def test_the_guard_is_a_live_filter_not_a_first_truthy_read():
    """Counter-proof anchor: the function must actually CONSULT the seed-owner set.

    Anchored on the AST rather than a byte window (#943), and it asserts the reference is
    inside `_scoped_reset_header` itself -- a module-level constant that nothing reads would
    satisfy a mere `in source` check while the hole stayed open.
    """
    tree = ast.parse(pathlib.Path(ce.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_scoped_reset_header")
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert "_SEED_OWNER_TENANTS_1202KU" in names, (
        "_scoped_reset_header no longer consults the seed-owner set")
    assert any(isinstance(n, ast.Compare)
               and any(isinstance(o, (ast.In, ast.NotIn)) for o in n.ops)
               for n in ast.walk(fn)), "the set is referenced but never tested against"
