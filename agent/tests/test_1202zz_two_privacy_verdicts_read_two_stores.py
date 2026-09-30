r"""#1202zz: two functions, one ticket, one name — and two different stores.

`_declared_owner_private_1202ht` exists twice:

    route_projector._declared_owner_private_1202ht(meta)
        -> meta["visibility"], the ORM model meta that `_stamp_spec_visibility_1202og` fills
           from `design/reference_spec.json`
    backend_skeleton._declared_owner_private_1202ht(tables, meta, path)
        -> resolves the table from the path, then the REGISTRY record's metadata.visibility

Same question — "do the materials call this table per-user private?" — asked of two stores. A
reader who assumes one implementation (as I did, an hour before writing this) will expect both
emitters to agree, and they need not: one would force owner-scope while the other releases the
read.

MEASURED over every corpus run carrying both a spec verdict and a registry verdict for the same
table: 174 agree, ONE disagrees — r137's `videos`, registry `text` against spec `public`. That
value is exactly what #1202vr now refuses at write time, so that disagreement can no longer be
stored. What stays reachable is a lane declaring `owner` on a table the materials call `public`;
no corpus run does it.

★ DELIBERATELY NOT COLLAPSED. Which store wins is #1202hh's and #1202gd's decision — "releasing a
read needs the materials AND the contract to agree" — and unifying these two here would settle it
by accident, at the two emitters that decide whether a projected read takes an actor. The fix is
that neither reader can be mistaken for the other's implementation again.
"""
import ast
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.backend_skeleton as BS  # noqa: E402
import multi_agent.runtime.route_projector as RP  # noqa: E402

_NAME = "_declared_owner_private_1202ht"


def _doc(mod):
    import inspect
    return inspect.getdoc(getattr(mod, _NAME)) or ""


def test_both_still_exist_with_different_signatures():
    """The premise. If one ever delegates to the other this test should be deleted, not loosened."""
    import inspect
    rp = list(inspect.signature(getattr(RP, _NAME)).parameters)
    bs = list(inspect.signature(getattr(BS, _NAME)).parameters)
    assert rp == ["meta"], rp
    assert bs == ["tables", "meta", "path"], bs


def test_each_names_the_other():
    for mod, other in ((RP, "backend_skeleton"), (BS, "route_projector")):
        d = _doc(mod)
        assert "#1202zz" in d, mod.__name__
        assert other in d, (mod.__name__, d[-300:])


def test_each_names_the_store_it_reads():
    assert "reference_spec.json" in _doc(RP)
    assert "REGISTRY" in _doc(BS)


def test_the_measurement_is_recorded():
    """174 / 1 is what makes "latent, not live" a statement rather than a hope."""
    for mod in (RP, BS):
        d = _doc(mod)
        assert "174" in d, mod.__name__
        assert "r137" in d, mod.__name__


def test_they_still_read_different_stores():
    """★ Structural, not textual: the day one of them starts reading the other's store the note
    above becomes the lie it was written to prevent."""
    import inspect
    rp_src = inspect.getsource(getattr(RP, _NAME))
    bs_src = inspect.getsource(getattr(BS, _NAME))
    rp_body = ast.parse(rp_src.lstrip()).body[0]
    bs_body = ast.parse(bs_src.lstrip()).body[0]
    rp_names = {n.id for n in ast.walk(rp_body) if isinstance(n, ast.Name)}
    bs_names = {n.id for n in ast.walk(bs_body) if isinstance(n, ast.Name)}
    assert "tables" in bs_names, "the registry reader no longer takes the table store"
    assert "tables" not in rp_names, "the model-meta reader started reading the registry"
