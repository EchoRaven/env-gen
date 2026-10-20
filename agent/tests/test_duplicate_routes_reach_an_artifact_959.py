r"""#959: #780 exists to stop this finding being log-only, and it is log-only in 153 of 154 runs.

#615 reports "N routes render identical content — all fetch only X". #780 turns that into a P1
fidelity task, but the filing sits behind `if _f708:` — only when the framework can derive WHICH
filter each route should pass. When it cannot, the finding falls back to a log line, which is
precisely the state #780 was written to end.

Measured: **one such task exists across the whole corpus, in 1 run of 154**, while #615 fires
routinely — twice in a single gate evaluation on r154:

    /browse/languages, /games, /shows   all fetch only /api/titles
    /movies, /new                       all fetch only /api/titles/top10

Five nav destinations showing the same list is a real fidelity defect, and #615's own message says
the visual gate cannot see it. Writing it to `design/duplicate_routes_959.json` costs nothing and
changes no behaviour; filing a task on every run would change what agents do, which needs a live
run to validate (#956/#957/#958's disposition).
"""
import json
import pathlib
import tempfile
import types

import pytest

from env_generator.llm_generator.multi_agent.runtime import deliverability as dl1203pg
from env_generator.llm_generator.multi_agent.runtime import frontend_audit as fa1203pg


def _artifact_writer_src():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import deliverability as dl
    return inspect.getsource(dl)


def test_the_finding_is_written_next_to_the_log_line():
    src = _artifact_writer_src()
    i = src.index("#959")
    j = src.index("#615 %d routes render identical", i)
    block = src[i:j]
    assert "duplicate_routes_959.json" in block
    assert "write_text" in block


def test_it_records_whether_780_managed_to_file_a_task():
    """★ The distinction that explains the corpus: with a derivable filter #780 files a task, and
    without one the finding used to vanish. The artifact must say which happened.

    ★★ Anchored on the AST node, not a byte window — #943's ratchet caught the first version of
    this file writing `src[i:i + 2600]` twice, which is exactly the shape it exists to stop. It
    fired on its author within the hour."""
    import ast
    src = _artifact_writer_src()
    keys = [k.value for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Dict)
            for k in n.keys if isinstance(k, ast.Constant) and k.value == "task_filed"]
    assert keys, "the artifact record must carry task_filed"
    calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "bool"
             and n.args and getattr(n.args[0], "id", None) == "_f708"]
    assert calls, "task_filed must be derived from _f708, the condition that gates #780"


def test_it_records_the_endpoints_not_just_the_routes():
    """`/movies` and `/new` are duplicates BECAUSE both fetch only /api/titles/top10 — the routes
    alone do not carry the reason."""
    import ast
    src = _artifact_writer_src()
    dicts = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Dict)
             and {k.value for k in n.keys if isinstance(k, ast.Constant)} >= {"routes", "endpoints",
                                                                              "components"}]
    assert dicts, "the record must carry the endpoints that make the routes duplicates"


def test_the_writer_cannot_break_the_gate():
    """Observability must never break what it observes — the gate decides whether to ship."""
    src = _artifact_writer_src()
    i = src.index("#959")
    block = src[i:src.index("#615 %d routes render identical", i)]
    assert "except Exception" in block


def test_the_corpus_premise_holds():
    """★ If #780 starts filing tasks routinely this ticket's premise is wrong and the test should
    say so rather than rot."""
    gen = pathlib.Path(__file__).resolve().parents[2] / "generated"
    files = list(gen.glob("*/shared/hubs/workhub_tasks.json"))
    if not files:
        pytest.skip("no runs on this box")
    n = 0
    for f in files:
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        n += sum(1 for k, v in d.items()
                 if k != "_meta" and isinstance(v, dict)
                 and "render identical" in ((v.get("title") or "") + (v.get("description") or "")))
    assert n <= 3, f"#780 now files these routinely ({n}); #959's premise needs revisiting"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))


# --- #1203pg: the artifact is really written -----------------------------------------------------
#
# Every assertion above reads the SOURCE of the writer. The whole point of #959 is that the
# finding reaches DISK even when #780 cannot derive a filter and falls back to a log line --
# which is 153 of 154 corpus runs -- so "a file appears, with these fields in it" is the
# property, and it can be driven: `_ui_page_wiring_blockers` takes a hub and an app_root, and
# `duplicate_route_content_groups` is a module-level function that can be injected.
#
# The artifact lands at `<app_root>/../design/duplicate_routes_959.json` (raw design/, outside
# app/, per #1202ts), so these tests read it back rather than trusting the writer's source.

_GROUP_959 = {"routes": ["/browse", "/movies"], "endpoints": ["/api/titles"],
              "components": ["TitleList"]}


@pytest.fixture(autouse=True)
def _reset_said_700_1203pg():
    """`_SAID_700` is a MODULE-level dedupe: once a group's key is in it, every later tick skips
    that group. Without this each test after the first silently exercised nothing -- it passed
    alone and failed in the file, which is the symptom worth remembering.
    """
    dl1203pg.reset_said_700()
    yield
    dl1203pg.reset_said_700()


def _run_959(monkeypatch, endpoints=None, group=None):
    """Run the reporter once; return (artifact dict or None, tasks filed)."""
    created = []
    root = pathlib.Path(tempfile.mkdtemp())
    app = root / "app"
    (app / "frontend" / "src").mkdir(parents=True)
    pages = {"p1": {"route": "/browse", "apis_used": ["/api/titles"]},
             "p2": {"route": "/movies", "apis_used": ["/api/titles"]}}
    hub = types.SimpleNamespace(
        workhub=types.SimpleNamespace(
            list_tasks=lambda: [], get_ui_pages=lambda: pages,
            create_task=lambda **kw: (created.append(kw), {"id": "t1"})[1]),
        registryhub=types.SimpleNamespace(
            get_endpoints=lambda: endpoints if endpoints is not None else {},
            get_ui_pages=lambda: pages))
    monkeypatch.setattr(fa1203pg, "duplicate_route_content_groups",
                        lambda *a, **k: [dict(group or _GROUP_959)])
    dl1203pg._ui_page_wiring_blockers(hub, app)
    f = root / "design" / "duplicate_routes_959.json"
    return (json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None), created


def test_the_artifact_is_written_even_when_780_cannot_file(monkeypatch):
    """The 153-of-154 case: no derivable filter, so #780 falls back to a log line. The artifact
    is the whole reason the finding is not lost."""
    art, created = _run_959(monkeypatch, endpoints={})
    assert created == [], "precondition: #780 should not have been able to file"
    assert art, "the finding was log-only -- exactly the state #959 exists to end"


def test_the_record_names_the_routes_and_the_endpoints(monkeypatch):
    art, _ = _run_959(monkeypatch, endpoints={})
    rec = list(art.values())[0]
    assert sorted(rec["routes"]) == ["/browse", "/movies"], rec
    assert rec["endpoints"] == ["/api/titles"], (
        "without the endpoints a reader cannot tell WHY the routes are duplicates")


def test_task_filed_is_FALSE_when_780_could_not_file(monkeypatch):
    art, created = _run_959(monkeypatch, endpoints={})
    assert created == []
    assert list(art.values())[0]["task_filed"] is False


def test_task_filed_is_TRUE_when_780_did_file(monkeypatch):
    """The one run in 154. Both readings have to be distinguishable on disk, or the artifact
    cannot answer the question it was added for."""
    eps = {"e1": {"path": "/api/titles",
                  "schema": {"request": {"genre": "str?", "kind": "str?"}}}}
    art, created = _run_959(monkeypatch, endpoints=eps)
    assert len(created) == 1, "precondition: #780 should have filed here"
    assert list(art.values())[0]["task_filed"] is True


def test_a_LATER_TICK_merges_rather_than_overwriting(monkeypatch):
    """The writer reads the previous file back before writing. Two ticks over the SAME tree must
    both survive, or the artifact holds only whatever the last tick happened to see.

    The first version of this test used a fresh temp root per run and asserted `len(art) == 1`,
    which cannot fail whether the merge works or not -- it was testing nothing.
    """
    root = pathlib.Path(tempfile.mkdtemp())
    app = root / "app"
    (app / "frontend" / "src").mkdir(parents=True)
    pages = {"p1": {"route": "/browse", "apis_used": ["/api/titles"]}}
    hub = types.SimpleNamespace(
        workhub=types.SimpleNamespace(list_tasks=lambda: [], get_ui_pages=lambda: pages,
                                      create_task=lambda **kw: {"id": "t"}),
        registryhub=types.SimpleNamespace(get_endpoints=lambda: {},
                                          get_ui_pages=lambda: pages))
    f = root / "design" / "duplicate_routes_959.json"

    monkeypatch.setattr(fa1203pg, "duplicate_route_content_groups",
                        lambda *a, **k: [dict(_GROUP_959)])
    dl1203pg._ui_page_wiring_blockers(hub, app)
    first = json.loads(f.read_text(encoding="utf-8"))
    assert len(first) == 1, first

    dl1203pg.reset_said_700()            # a later tick, same tree
    monkeypatch.setattr(fa1203pg, "duplicate_route_content_groups", lambda *a, **k: [
        {"routes": ["/new", "/shows"], "endpoints": ["/api/titles"], "components": []}])
    dl1203pg._ui_page_wiring_blockers(hub, app)
    second = json.loads(f.read_text(encoding="utf-8"))
    assert len(second) == 2, (
        "the later tick overwrote the earlier group instead of merging: %s" % second)
    assert set(first) <= set(second)


def test_two_groups_in_one_tree_both_land(monkeypatch):
    created = []
    root = pathlib.Path(tempfile.mkdtemp())
    app = root / "app"
    (app / "frontend" / "src").mkdir(parents=True)
    pages = {"p1": {"route": "/browse", "apis_used": ["/api/titles"]}}
    hub = types.SimpleNamespace(
        workhub=types.SimpleNamespace(
            list_tasks=lambda: [], get_ui_pages=lambda: pages,
            create_task=lambda **kw: (created.append(kw), {"id": "t1"})[1]),
        registryhub=types.SimpleNamespace(get_endpoints=lambda: {},
                                          get_ui_pages=lambda: pages))
    monkeypatch.setattr(fa1203pg, "duplicate_route_content_groups", lambda *a, **k: [
        dict(_GROUP_959),
        {"routes": ["/new", "/shows"], "endpoints": ["/api/titles"], "components": []}])
    dl1203pg._ui_page_wiring_blockers(hub, app)
    art = json.loads((root / "design" / "duplicate_routes_959.json").read_text(encoding="utf-8"))
    assert len(art) == 2, art


def test_nothing_is_written_when_there_are_no_duplicate_groups(monkeypatch):
    """Non-vacuity: a writer that always wrote would satisfy every test above."""
    art, _ = _run_959(monkeypatch, endpoints={}, group=None)
    assert art is not None
    root2 = pathlib.Path(tempfile.mkdtemp())
    app2 = root2 / "app"
    (app2 / "frontend" / "src").mkdir(parents=True)
    hub = types.SimpleNamespace(
        workhub=types.SimpleNamespace(list_tasks=lambda: [], get_ui_pages=lambda: {},
                                      create_task=lambda **kw: {"id": "t"}),
        registryhub=types.SimpleNamespace(get_endpoints=lambda: {}, get_ui_pages=lambda: {}))
    monkeypatch.setattr(fa1203pg, "duplicate_route_content_groups", lambda *a, **k: [])
    dl1203pg._ui_page_wiring_blockers(hub, app2)
    assert not (root2 / "design" / "duplicate_routes_959.json").is_file()
