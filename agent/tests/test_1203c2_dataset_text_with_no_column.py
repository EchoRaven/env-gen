r"""#1203c2: the dataset's content field has no column to land in, and nothing says so.

The framework stages `app/backend/seed_dataset.json` from its real-content corpus; the lane
declares the columns. When the dataset's text field has no column of that name, the text is
dropped on load and the rows arrive empty.

r145, measured against its own artifacts:
  · `seed_dataset.json` holds 35 videos whose text is in `caption`
    ('#KEEPSWIMMING with BTS.  To everyone who keeps swimming no matter wha.')
    while `models.py`'s `Video` has `title` / `description` and no `caption`
  · it holds 295 comments whose text is in `text` ('who else is here in 2026')
    while that run's `Comment` names the column `body`
  → 330 pieces of real content dropped in one run. `curl /api/feed` returns
    `title: null, description: null` over real `video_url`s, the page renders a player with no
    words, the walk finds no seed text on `/`, and `primary_dataless` holds — a signal
    `browser_gate_decision` puts in the HARD set, which never escape-releases.

r144 is the negative control: its `Comment` DOES name the column `text`, and the detector
reports nothing for it. Corpus: 7 of 140 runs lose a content field this way.

NOTHING ELSE REPORTS IT. `seed_audit` states in its own words that "Extra live columns are not
reported", and in r145 it examined 0 of 4/5/7 tables anyway. `caption` appears ONCE in that
run's log — the backend agent grepping for it, with nothing to find.

Reported, never repaired and never guessed: which column the product means is the lane's to
decide, and mapping `caption` onto `description` would be a guess.
"""
import asyncio
import json
import os
import sys
import types

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime.seed_audit import SeedReport  # noqa: E402
import tools.seed_tools as ST  # noqa: E402

_KEY = "dataset_text_without_column_1203c2"


def _F(project_dir):
    """Looked up per call, not at import: a module-level reference turns a missing function into
    a COLLECTION error, which reports as one broken file instead of the specific assertions that
    fail."""
    fn = getattr(ST, "_unmapped_dataset_text_1203c2", None)
    assert fn is not None, "_unmapped_dataset_text_1203c2 is not defined"
    return fn(project_dir)


def _tree(tmp_path, dataset, models_src):
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (be / "seed_dataset.json").write_text(json.dumps(dataset), encoding="utf-8")
    (be / "models.py").write_text(models_src, encoding="utf-8")
    return tmp_path


_VIDEO_MODEL = (
    "class Video(Base):\n"
    "    __tablename__ = 'videos'\n"
    "    id = Column(Integer, primary_key=True)\n"
    "    title = Column(String)\n"
    "    description = Column(Text)\n"
    "    video_url = Column(String)\n")


def test_r145s_caption_is_reported(tmp_path):
    """★ The exact shape that cost r145 the run."""
    p = _tree(tmp_path, {"videos": [{"id": 1, "caption": "#KEEPSWIMMING with BTS.",
                                     "video_url": "/a.mp4"}]}, _VIDEO_MODEL)
    assert _F(p) == {"videos": ["caption"]}, _F(p)


def test_a_column_of_that_name_reports_nothing(tmp_path):
    """r144's negative control: its `Comment` names the column `text`, so nothing is lost."""
    p = _tree(tmp_path, {"comments": [{"id": 1, "text": "who else is here in 2026"}]},
              "class Comment(Base):\n"
              "    __tablename__ = 'comments'\n"
              "    id = Column(Integer, primary_key=True)\n"
              "    text = Column(Text)\n")
    assert _F(p) == {}, _F(p)


def test_a_differently_named_column_is_still_a_loss(tmp_path):
    """r145's `Comment` has `body` while the dataset has `text` — 295 comment texts dropped."""
    p = _tree(tmp_path, {"comments": [{"id": 1, "text": "who else is here in 2026"}]},
              "class Comment(Base):\n"
              "    __tablename__ = 'comments'\n"
              "    id = Column(Integer, primary_key=True)\n"
              "    body = Column(Text)\n")
    assert _F(p) == {"comments": ["text"]}, _F(p)


def test_counts_and_relations_are_not_reported(tmp_path):
    """★ Narrow on purpose. A dataset's `likes` or `author_id` is a count the projector derives
    or a relation the loader resolves; naming them would bury the one field that matters
    (#1202vx: the explanation must not spend the evidence budget)."""
    p = _tree(tmp_path, {"videos": [{"id": 1, "likes": 99, "author_id": 3, "views": 5,
                                     "thumbnail": "/t.png", "caption": "real words"}]},
              _VIDEO_MODEL)
    assert _F(p) == {"videos": ["caption"]}, _F(p)


def test_an_empty_field_is_not_a_loss(tmp_path):
    """A field present but blank in every row loses nothing — reporting it would be noise."""
    p = _tree(tmp_path, {"videos": [{"id": 1, "caption": ""}, {"id": 2, "caption": "   "}]},
              _VIDEO_MODEL)
    assert _F(p) == {}, _F(p)


def test_unparseable_models_make_no_claim(tmp_path):
    """★ No models parsed means no knowledge of the columns, so no accusation."""
    p = _tree(tmp_path, {"videos": [{"id": 1, "caption": "x y z"}]}, "def (((")
    assert _F(p) == {}
    p2 = _tree(tmp_path / "b", {"videos": [{"id": 1, "caption": "x y z"}]}, "# no columns here\n")
    assert _F(p2) == {}


def test_a_missing_tree_is_silent(tmp_path):
    assert _F(tmp_path / "nope") == {}
    assert _F(None) == {}


def test_the_tool_reports_it_where_the_agent_reads(tmp_path, monkeypatch):
    """★ The whole placement argument: the framework's seed audit says "Extra live columns are
    not reported" and the log the lane cannot see is where everything else lands."""
    p = _tree(tmp_path, {"videos": [{"id": 1, "caption": "#KEEPSWIMMING with BTS."}]},
              _VIDEO_MODEL)
    monkeypatch.setattr(ST, "audit_seed_data",
                        lambda *a, **k: SeedReport(flagged_tables=[], examined=4, candidates=4))
    monkeypatch.setattr(ST, "_project_dir_1202q", lambda *a, **k: p)
    res = asyncio.run(ST.SeedAuditCheckTool(hub_registry=types.SimpleNamespace()).execute())
    d = res.data if hasattr(res, "data") else res["data"]
    assert _KEY in d, sorted(d)
    assert d[_KEY]["unmapped"] == {"videos": ["caption"]}
    assert "dropped on load" in d[_KEY]["note"]
    assert "do not leave the rows wordless" in d[_KEY]["note"]


def test_a_clean_tree_adds_no_field(tmp_path, monkeypatch):
    """No noise when nothing is lost — the payload is byte-identical to before."""
    p = _tree(tmp_path, {"videos": [{"id": 1, "title": "Real Title"}]}, _VIDEO_MODEL)
    monkeypatch.setattr(ST, "audit_seed_data",
                        lambda *a, **k: SeedReport(flagged_tables=[], examined=4, candidates=4))
    monkeypatch.setattr(ST, "_project_dir_1202q", lambda *a, **k: p)
    res = asyncio.run(ST.SeedAuditCheckTool(hub_registry=types.SimpleNamespace()).execute())
    d = res.data if hasattr(res, "data") else res["data"]
    assert _KEY not in d, d


def test_it_does_not_guess_a_mapping():
    """★ The lane owns the schema. A fix that renamed `caption` to `description` would decide
    which column the product means — pinned so a later edit does not quietly start guessing."""
    import inspect
    fn = getattr(ST, "_unmapped_dataset_text_1203c2", None)
    assert fn is not None, "_unmapped_dataset_text_1203c2 is not defined"
    src = inspect.getsource(fn)
    for verb in ("rename", "setdefault", "update(", "write_text", "dump"):
        assert verb not in src, "the reporter mutates something: %r" % verb
