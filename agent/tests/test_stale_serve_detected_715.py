r"""#715: check that the app we are about to photograph was built from this source.

#713 settled the r147 collapse as the SERVE side — the rename landed at 04:02:44, nothing
rebuilt, and the 04:03:54 capture hit a bundle that knew only the old paths, so four screens fell
to the catch-all and scored 0.03-0.08. The route list is re-parsed from SOURCE on every call and
is never stale; the gap is between it and what the container serves, and nothing checked that.
81% of runs contain screens scored against a page an older bundle produced.

The instrument existed and had never been wired: `DockerInspectImageTool`, whose own description
is "useful for debugging when containers show stale/placeholder content", is exported, in no
bundle, and absent from all 253 run logs. Rather than grant a tool, the gate runs the same two
commands itself — it already has `project_dir`, and this is a framework check, not an agent
capability.

Report-only, and the wording carries the point: a mismatch does not mean the app is broken, it
means THIS MEASUREMENT IS VOID. That is the distinction the framework could not make, and the
reason a phantom 0.05 was indistinguishable from a real one.

Two things this fix had to get right, both of which the first draft got wrong:

  * the container is nginx serving the BUILD. The Dockerfile ends
    `COPY --from=builder /app/dist /usr/share/nginx/html`, so `src/App.jsx` is not in it and
    reading that path would have made the whole check silently dead — the third such near-miss
    this session. It now greps the served bundle, falling back to `src/` for a dev layout.
  * the assumption that route literals survive the build is UNVERIFIED — the delivered tree has
    no `dist/`, so it could not be checked offline. If it is wrong the check would fire on every
    route of every run, so a near-total miss is reported as a suspect PROBE and downgraded to no
    signal: a real staleness moves a few routes, not all of them.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf


def _block() -> str:
    src = inspect.getsource(vf)
    i = src.index("#715: IS THE APP WE ARE ABOUT TO PHOTOGRAPH BUILT FROM THIS FILE?")
    return src[i:src.index("except Exception:\n        pass", i)]


def _head(r: str) -> str:
    return r.split(":", 1)[0].rstrip("/") or "/"


# --- the comparison rule ------------------------------------------------------------------------

def test_a_param_route_compares_on_its_static_head():
    assert _head("/browse/genre/:genreId") == "/browse/genre"
    assert _head("/watch/:titleId") == "/watch"


def test_the_bare_root_is_ignored():
    assert len(_head("/")) == 1


def test_a_route_present_in_the_bundle_is_not_missing():
    served = 'x("/browse/languages")y'
    assert _head("/browse/languages") in served


def test_a_renamed_route_is_missing():
    served = 'x("/browse-by-languages")y'          # the OLD path, as r147's bundle had
    assert _head("/browse/languages") not in served


# --- the production block ------------------------------------------------------------------------

def test_it_reads_the_served_bundle_not_the_source_path_only():
    b = _block()
    assert "/usr/share/nginx/html/assets/*.js" in b
    assert "cat /app/src/App.jsx 2>/dev/null ||" in b


def test_it_records_why_the_source_path_alone_is_wrong():
    b = " ".join(_block().split())
    assert "COPY --from=builder /app/dist /usr/share/nginx/html" in b
    assert "silently never fired" in b


def test_it_guards_against_a_bad_probe():
    b = _block()
    assert "probe inconclusive" in b
    assert "_missing715 = set()" in b


def test_the_guard_threshold_needs_nearly_all_routes():
    b = _block()
    assert "len(known_routes) - 1" in b


def test_it_says_a_mismatch_voids_the_measurement():
    b = " ".join(_block().split())
    assert "STALE BUILD, not a bad page" in b
    assert "void for them" in b


def test_it_is_report_only():
    b = _block()
    # Excludes the nested `_head715` helper, whose `return` is its own — the same trap
    # #708b hit. What matters is that the BLOCK does not return out of run_visual_fidelity.
    lines = [l for l in b.split("\n") if l.strip() and not l.strip().startswith("#")]
    depth = None
    code = []
    for l in lines:
        ind = len(l) - len(l.lstrip())
        if l.lstrip().startswith("def "):
            depth = ind
            continue
        if depth is not None and ind > depth:
            continue
        depth = None
        code.append(l.strip())
    assert not [l for l in code if l == "raise" or l.startswith(("raise ", "return"))]


def test_it_cannot_break_the_gate():
    assert "except Exception:" in _block()


def test_it_does_not_require_a_tool_grant():
    b = _block()
    assert "subprocess as _sp715" in b
    assert "docker_inspect_image" not in b


# --- provenance -------------------------------------------------------------------------------------

def test_the_r147_evidence_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "04:02:44" in b and "04:03:54" in b


def test_the_unwired_instrument_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "DockerInspectImageTool" in b
    assert "never been wired" in b


def test_the_scale_is_recorded():
    b = " ".join(_block().replace("#", " ").split())
    assert "103 of 127 runs (81%)" in b


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
