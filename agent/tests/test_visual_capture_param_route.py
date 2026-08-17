"""#418 (2026-08-02): the visual-capture navigation visited a param route with the
LITERAL param (page.goto(base_url + '/title/:id')) → the app fetched title ':id'
→ 404 → the page's empty-state rendered → the judge scored a data-less page ~0.00
regardless of layout/projection quality (r13: genre_category /browse/genre/:genreId
= 0.00, player /watch/:titleId = 0.10 — the detail screens the projector builds
hero+rails for). FIX: _concrete_capture_route fills every :param / {param} segment
with a real seeded id ('1' — serial PKs start at 1 and the seed loader always
seeds >=1 row per table, the same id-1 assumption #411's FK repair uses). This
locks the substitution in (and that it is a no-op for param-less routes, so
non-detail screens are unaffected).

Self-contained harness (mirrors test_visual_gate_wiring_precondition.py): stub the
one sibling import, exec the module under a synthetic package."""
import sys
import types
from pathlib import Path

_SRC = (Path(__file__).resolve().parents[1] / "env_generator" / "llm_generator"
        / "multi_agent" / "runtime" / "visual_fidelity.py")


def _load():
    pkg = types.ModuleType("vf_pkg")
    pkg.__path__ = []
    vr = types.ModuleType("vf_pkg.validation_runner")
    vr._service_host_port = lambda *a, **k: None
    sys.modules["vf_pkg"] = pkg
    sys.modules["vf_pkg.validation_runner"] = vr
    # #898: `visual_fidelity` derives its ceilings via `stage_contract.llm_ceiling_898`, imported
    # inside the accessor. This harness hand-stubs each module the source reaches, so a new one
    # must be added here too — the same contract `validation_runner` above is satisfying.
    import env_generator.llm_generator.multi_agent.runtime.stage_contract as _sc
    sys.modules["vf_pkg.stage_contract"] = _sc
    mod = types.ModuleType("vf_pkg.visual_fidelity")
    mod.__package__ = "vf_pkg"
    exec(compile(_SRC.read_text(encoding="utf-8"), str(_SRC), "exec"), mod.__dict__)
    return mod


VF = _load()
_f = VF._concrete_capture_route


def test_colon_param_filled_with_seeded_id():
    assert _f("/title/:id") == "/title/1"
    assert _f("/watch/:titleId") == "/watch/1"
    assert _f("/browse/genre/:genreId") == "/browse/genre/1"


def test_brace_param_filled():
    assert _f("/title/{id}") == "/title/1"
    assert _f("/genres/{genreId}/titles") == "/genres/1/titles"


def test_mid_path_and_multi_param():
    assert _f("/title/:id/episodes") == "/title/1/episodes"
    assert _f("/u/:userId/list/:listId") == "/u/1/list/1"


def test_paramless_routes_unchanged():
    for r in ("/", "/browse", "/movies", "/my-list", "/browse/languages", "/login"):
        assert _f(r) == r, f"param-less route {r} must be untouched"


def test_empty_and_none_safe():
    assert _f("") == ""
    assert _f(None) is None


def test_does_not_eat_literal_segments_that_look_wordy():
    # only :x / {x} are params; a literal 'genre' segment stays
    assert _f("/browse/genre/:genreId") == "/browse/genre/1"
    assert _f("/new") == "/new"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
