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

import pytest


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
    gen = pathlib.Path(__file__).resolve().parents[1] / "generated"
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
