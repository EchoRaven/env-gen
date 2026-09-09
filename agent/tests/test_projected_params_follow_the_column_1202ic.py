r"""#1202ic: a projected handler keeps the param type it was born with.

`project_missing_routes` appends a handler for every declared endpoint that has NO route
and counts the rest as `already`. Correct for what it is — and it means a handler emitted
once is never revisited, so its param type outlives the column it was derived from.

tiktok-r107, live while this was written. `app/backend/models.py` git history, one commit
every 6.3 minutes:

    faf536f  videos.id  Integer -> Text
    68a25b2             Text -> Integer
    1f19c23             Integer -> Text
    f5722ad             Text -> Integer

The lane is oscillating on the PK type and this is one of its engines: the seven projected
`/api/videos/{id}...` handlers were born `id: int`, so while the column is Text every
request carrying a uuid is rejected by FastAPI with `int_parsing` 422 BEFORE the handler
body runs — 34 such 422s across the corpus. The lane reads "not a valid integer", changes
the column, nothing improves, changes it back. `_param_column_type` asked against the
current models.py had the right answer the whole time, for a caller that never asked again.

Only `_projected_*` functions are touched: that prefix is stamped by `_generate_handler`
and nothing a lane writes carries it, so lane code is out of reach by construction.
"""
from __future__ import annotations

import textwrap

from env_generator.llm_generator.multi_agent.runtime.route_projector import (
    _retype_projected_params_1202ic as retype,
)

MODELS_TEXT_PK = {"videos": {"cols": ["id", "caption"], "types": {"id": "Text"}}}
MODELS_INT_PK = {"videos": {"cols": ["id", "caption"], "types": {"id": "Integer"}}}


def _src(annotation: str) -> str:
    return textwrap.dedent(f"""\
        from fastapi import FastAPI, Depends
        app = FastAPI()

        @app.get("/api/videos/{{id}}")
        def _projected_get_api_videos_id_1(id: {annotation}, db=Depends(get_db)):
            return {{}}
        """)


def test_a_text_column_retypes_an_int_param(monkeypatch):
    """The r107 case: column moved to Text, handler still says int."""
    import env_generator.llm_generator.multi_agent.runtime.route_projector as RP
    monkeypatch.setattr(RP, "_param_column_type", lambda p, path, m: "str")
    new, changed = retype(_src("int"), MODELS_TEXT_PK)
    assert changed, "the mismatch must be found"
    assert "id: str" in new and "id: int" not in new


def test_an_agreeing_type_is_left_alone(monkeypatch):
    import env_generator.llm_generator.multi_agent.runtime.route_projector as RP
    monkeypatch.setattr(RP, "_param_column_type", lambda p, path, m: "int")
    src = _src("int")
    new, changed = retype(src, MODELS_INT_PK)
    assert not changed and new == src, "an agreeing handler must be byte-identical"


def test_it_retypes_the_other_direction_too(monkeypatch):
    """The oscillation goes both ways; so must the correction."""
    import env_generator.llm_generator.multi_agent.runtime.route_projector as RP
    monkeypatch.setattr(RP, "_param_column_type", lambda p, path, m: "int")
    new, changed = retype(_src("str"), MODELS_INT_PK)
    assert changed and "id: int" in new


def test_lane_authored_handlers_are_never_touched(monkeypatch):
    """The safety property. A lane's own route is not ours to rewrite."""
    import env_generator.llm_generator.multi_agent.runtime.route_projector as RP
    monkeypatch.setattr(RP, "_param_column_type", lambda p, path, m: "str")
    src = textwrap.dedent("""\
        @app.get("/api/videos/{id}")
        def get_video(id: int, db=Depends(get_db)):
            return {}
        """)
    new, changed = retype(src, MODELS_TEXT_PK)
    assert not changed and new == src, "only _projected_* may be rewritten"


def test_a_static_route_is_skipped(monkeypatch):
    import env_generator.llm_generator.multi_agent.runtime.route_projector as RP
    monkeypatch.setattr(RP, "_param_column_type", lambda p, path, m: "str")
    src = textwrap.dedent("""\
        @app.get("/api/videos")
        def _projected_get_api_videos_0(db=Depends(get_db)):
            return {}
        """)
    assert retype(src, MODELS_TEXT_PK) == (src, [])


def test_undecorated_or_odd_annotations_are_left_alone(monkeypatch):
    import env_generator.llm_generator.multi_agent.runtime.route_projector as RP
    monkeypatch.setattr(RP, "_param_column_type", lambda p, path, m: "str")
    src = textwrap.dedent("""\
        @app.get("/api/videos/{id}")
        def _projected_get_api_videos_id_1(id: SomeCustomType, db=Depends(get_db)):
            return {}
        """)
    assert retype(src, MODELS_TEXT_PK) == (src, [])


def test_unparseable_source_is_returned_unchanged():
    """A syntax error in main.py must not be the reason a run dies here."""
    bad = "def broken(:\n"
    assert retype(bad, MODELS_TEXT_PK) == (bad, [])


def test_it_reports_what_it_changed(monkeypatch):
    import env_generator.llm_generator.multi_agent.runtime.route_projector as RP
    monkeypatch.setattr(RP, "_param_column_type", lambda p, path, m: "str")
    _, changed = retype(_src("int"), MODELS_TEXT_PK)
    assert any("id: int -> str" in c for c in changed)


# --- reachability ---------------------------------------------------------------

def test_it_runs_on_every_projection_pass_not_only_when_routes_are_added():
    """A run where nothing is MISSING still needs its types re-derived; that is exactly
    the state a mid-run schema flip leaves behind."""
    import ast, inspect
    from env_generator.llm_generator.multi_agent.runtime import route_projector as RP
    fn = ast.parse(inspect.getsource(RP.project_missing_routes).lstrip()).body[0]
    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "_retype_projected_params_1202ic"]
    assert calls, "the pass is never invoked"
    # It must sit at function top level, not inside a conditional that only fires when
    # something was projected.
    top = [n for n in fn.body if any(
        isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
        and c.func.id == "_retype_projected_params_1202ic" for c in ast.walk(n))]
    assert top and not isinstance(top[0], ast.If), (
        "guarded by a conditional — the no-new-routes case is the one that needed it")


def test_the_result_is_reported_to_the_caller():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import route_projector as RP
    src = inspect.getsource(RP.project_missing_routes)
    assert "retyped_1202ic" in src.split("return {")[-1], "the caller cannot see it happened"
