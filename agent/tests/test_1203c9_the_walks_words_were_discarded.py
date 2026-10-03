r"""#1203c9: the costliest call in the run answers, and one bad character discards the answer.

`_ui_test_user` sends 8 high-detail screenshots in ONE multimodal call and asks the model, per
screen, what works and what the problems are — then throws the response away on any exception:

    text = getattr(resp, "content", "") or ""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    data = json.loads(m.group(0)) if m else {}
    ...
    except Exception as exc:
        return {"ran": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}

MEASURED over all 199 reports carrying `ui.ran`: 152 ran, 23 said "no screenshots or no llm",
**21 died on JSONDecodeError**, 3 on 429/400/connection.

★ I RULED OUT MY FIRST TWO EXPLANATIONS, both by measurement:
  * TRUNCATION (`max_tokens=3000`): the largest of the 152 successful outputs is ~2039 estimated
    tokens and ZERO reach 80% of the cap (median 1309).
  * THE GREEDY `\{.*\}` SPAN swallowing trailing prose: reproduced — it raises `Extra data`, not
    the `Expecting ',' delimiter` every corpus failure shows.
  What produces that exact message is an unescaped double quote inside a string value, or a
  missing comma between items: the MODEL emitted invalid JSON. So the parse is not the defect.
  The LOSS is.

★ NO REPAIR, DELIBERATELY. Guessing where a quote belonged would invent findings, and the
standing rule is that a fallback masking a failure is worse than none. The failure stays a
failure with the same exception text; the words are kept so the walk is not lost.
"""
import json
import os
import sys
import types

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.test_user_validation as TUV  # noqa: E402

# Exactly the shape the corpus fails on: an unescaped quote inside a string value.
_BAD = ('{"screens": [{"name": "feed", "works": "the "Follow" button works", '
        '"problems": ["the grid is cut off on the right"]}], "top_issues": ["fix the grid"]}')
_GOOD = ('{"screens": [{"name": "feed", "works": "ok", "problems": ["cut off"]}], '
         '"top_issues": ["fix the grid"]}')


def _run(tmp_path, content, with_shots=True, llm=True, monkeypatch=None):
    import asyncio

    if with_shots:
        d = tmp_path / "design" / "visual_gate"
        d.mkdir(parents=True)
        (d / "feed.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    class _Client:
        async def chat(self, *a, **k):
            return types.SimpleNamespace(content=content)

    obj = types.SimpleNamespace(_client=_Client()) if llm else None
    if monkeypatch is not None:
        import multi_agent.runtime.visual_fidelity as VF
        monkeypatch.setattr(VF, "_b64", lambda *a, **k: "AAAA", raising=False)
    return asyncio.run(TUV._ui_test_user(tmp_path, obj))


def test_the_models_words_are_kept(monkeypatch, tmp_path):
    """★ The whole ticket: the findings existed and were discarded."""
    out = _run(tmp_path, _BAD, monkeypatch=monkeypatch)
    assert out["ran"] is False
    assert "cut off on the right" in out.get("raw_excerpt_1203c9", ""), out


def test_the_words_are_on_disk(monkeypatch, tmp_path):
    out = _run(tmp_path, _BAD, monkeypatch=monkeypatch)
    p = out.get("raw_saved_to_1203c9")
    assert p, out
    import pathlib
    assert "cut off on the right" in pathlib.Path(p).read_text(encoding="utf-8")


def test_the_failure_is_unchanged(monkeypatch, tmp_path):
    """★ Same exception text as before — this adds evidence, it does not soften the verdict."""
    out = _run(tmp_path, _BAD, monkeypatch=monkeypatch)
    assert out["ran"] is False
    assert "JSONDecodeError" in out["reason"], out["reason"]
    assert "Expecting ',' delimiter" in out["reason"], out["reason"]


def test_the_reason_says_the_model_did_answer(monkeypatch, tmp_path):
    """A reader who sees only a parser error concludes the walk did not happen."""
    r = _run(tmp_path, _BAD, monkeypatch=monkeypatch)["reason"]
    assert "DID answer" in r, r
    assert "logs/ui_test_user_raw_1203c9.txt" in r, r


def test_nothing_is_fabricated(monkeypatch, tmp_path):
    """★ No repair: a failed parse must not yield screens or top_issues, however tempting the
    text is to patch up."""
    out = _run(tmp_path, _BAD, monkeypatch=monkeypatch)
    assert not out.get("screens"), out
    assert not out.get("top_issues"), out


def test_a_long_response_says_what_it_cut(monkeypatch, tmp_path):
    """#1034: the excerpt is capped and the cap announces itself."""
    big = '{"screens": [{"name": "a", "works": "the "x" y' + ("z" * 3000) + '"}]}'
    out = _run(tmp_path, big, monkeypatch=monkeypatch)
    ex = out.get("raw_excerpt_1203c9", "")
    assert "not shown" in ex, ex[-200:]
    assert len(ex) < len(big)


def test_a_successful_parse_is_untouched(monkeypatch, tmp_path):
    """The success path must be byte-identical — no raw keys, no extra files."""
    out = _run(tmp_path, _GOOD, monkeypatch=monkeypatch)
    assert out["ran"] is True
    assert out["screens"] and out["top_issues"]
    assert "raw_excerpt_1203c9" not in out and "raw_saved_to_1203c9" not in out, out
    assert not (tmp_path / "logs" / "ui_test_user_raw_1203c9.txt").exists()


def test_no_llm_names_the_wiring_cause(monkeypatch, tmp_path):
    """★ 23 reports said "no screenshots or no llm". A reader cannot act on one-of-two."""
    out = _run(tmp_path, _GOOD, llm=False, monkeypatch=monkeypatch)
    assert out["ran"] is False
    assert "no llm" in out["reason"], out["reason"]
    assert " or " not in out["reason"], out["reason"]


def test_no_screenshots_names_the_timing_cause(monkeypatch, tmp_path):
    """The other half, and it is a TIMING fact like #616's — the visual gate may not have run."""
    out = _run(tmp_path, _GOOD, with_shots=False, monkeypatch=monkeypatch)
    assert out["ran"] is False
    assert "AT THIS MOMENT" in out["reason"], out["reason"]
    assert "visual_gate" in out["reason"], out["reason"]


def test_a_save_fault_still_keeps_the_excerpt(monkeypatch, tmp_path):
    """If the directory cannot be written, the words must still reach the report."""
    import pathlib
    real = pathlib.Path.write_text

    def _boom(self, *a, **k):
        if "ui_test_user_raw_1203c9" in str(self):
            raise OSError("read-only")
        return real(self, *a, **k)
    monkeypatch.setattr(pathlib.Path, "write_text", _boom)
    out = _run(tmp_path, _BAD, monkeypatch=monkeypatch)
    assert "cut off on the right" in out.get("raw_excerpt_1203c9", ""), out
    assert "raw_saved_to_1203c9" not in out, out


def test_no_second_parse_attempt_was_added():
    """★ Structural, so a later edit cannot turn this into a repairing parser: the function must
    call `json.loads` exactly once. A second call means something is retrying on mangled text,
    which is how invented findings would get in."""
    import ast
    import inspect

    src = inspect.getsource(TUV._ui_test_user)
    tree = ast.parse(src.lstrip())
    loads = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "attr", "") == "loads"]
    assert len(loads) == 1, "json.loads is called %d times" % len(loads)
