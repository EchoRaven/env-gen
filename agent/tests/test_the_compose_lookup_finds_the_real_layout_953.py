r"""#953: the stale-build probes searched for a compose file where no run puts one.

    probe looked at   project_dir / "docker-compose.yml"
    every run has it  project_dir / "docker" / "docker-compose.yml"   (r154, r153, r150)

So `_cf715` was None in every run and #715/#738 never reached the container lookup at all.
`_compose_up`, in this same module, has always used the `docker/` path — the knowledge was here
twice and the copies disagreed (#926's shape).

★ #936's docker-vs-podman fix was real but DOWNSTREAM of a lookup that never succeeded. The two
probes were dead for two independent reasons, and this one would have kept them dead on a docker
host as well. #738 exists because r148 shipped a v1.0.0 whose SPA crashed on every route.

★★ Found only by running the real pipeline against a real application. A synthetic test passes the
compose path in directly and therefore can never see a wrong lookup — which is why the four
synthetic integration runs earlier today all passed. With this fixed, against r154's live app:

    #936  compose ps -q returned nothing but the container IS running (b37c8517) — name filter
    #715  served build matches the source: all 14 declared route(s) present in the bundle
    served_build.json written — the first time in the corpus's history
"""
import ast
import inspect
import pathlib

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _candidates():
    """The literal filenames the probe tries, in order."""
    src = inspect.getsource(vf.run_visual_fidelity)
    i = src.index("_cf715 = None")
    j = src.index("if _cf715 is not None", i)
    tup = ast.parse(src[i:j].strip().splitlines()[1].strip().replace("for _c715 in ", "x = ")
                    .rstrip(":") ) if False else None
    # parse the for-loop's iterable properly
    for n in ast.walk(ast.parse(inspect.getsource(vf))):
        if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == "_c715":
            return [e.value for e in n.iter.elts if isinstance(e, ast.Constant)]
    return []


def test_the_docker_subdirectory_is_searched():
    """★ THE fix. Every run in the corpus keeps its compose under docker/."""
    c = _candidates()
    assert c, "the compose-candidate loop moved; this test needs re-anchoring"
    assert any(x.startswith("docker/") for x in c), c


def test_the_docker_subdirectory_is_searched_FIRST():
    """Root-level first would still work, but the real layout should not be the fallback."""
    c = _candidates()
    assert c[0].startswith("docker/"), c


def test_the_root_layout_is_still_supported():
    """A project that does keep it at the root must not regress."""
    assert "docker-compose.yml" in _candidates()


def test_it_matches_what_compose_up_uses():
    """★ #926's rule: the same knowledge written twice must not disagree. `_compose_up` has always
    used docker/docker-compose.yml; the probe now agrees with it."""
    up = inspect.getsource(vf._compose_up)
    assert '"docker" / "docker-compose.yml"' in up
    assert any(x == "docker/docker-compose.yml" for x in _candidates())


def test_the_corpus_layout_is_what_this_claims():
    """Non-vacuity against the real tree, so the premise cannot rot silently."""
    gen = pathlib.Path(__file__).resolve().parents[2] / "generated"
    runs = [d for d in gen.glob("netflix-web-r1*") if (d / "docker").is_dir()][:6]
    if not runs:
        pytest.skip("no generated runs on this box")
    for d in runs:
        assert (d / "docker" / "docker-compose.yml").is_file(), d
        assert not (d / "docker-compose.yml").is_file(), f"{d} has a ROOT compose — premise changed"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
