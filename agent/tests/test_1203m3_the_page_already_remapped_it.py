r"""#1203m3: the P1 said the card 404s on play, for paths the page already rewrites.

`#1202zf` files "Seeded media missing at delivery — cards render a thumbnail and 404 on
play" and instructs "Fix the SEED ROW, not the page". Measured over the modern corpus: 42
seed-side missing media in 7 runs, and 9 (21%, r166 and r172) are keys in a frontend remap
table whose value IS a staged file -- so for those the 404 cannot happen and the page is
exactly where the fix went. r172's table is `stagedVideoReplacements` in `services/api.js`,
consulted by `normalizeVideo`, applied by `getForYouFeed`.

Annotated, never dropped: the check proves a mapping exists, not that every caller goes
through it (r172 applies its map in one endpoint). The negative control is r181, whose own
validation record reads "six displayed /assets/real_videos/*.mp4 requests still failed" --
the predicate selects 0 there.
"""
from __future__ import annotations

import json

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold, heal_pipeline
from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    remapped_seed_media_1203m3)

MISSING = "/assets/real_videos/khaby.lame__7663376464665906452.mp4"
TARGET = "/assets/real_videos/khaby.lame__7661681676719869214.mp4"


def _tree(tmp_path, *, table_target=None, stage_target=True):
    """A run tree shaped like r172: one missing seed path, optionally remapped."""
    fe = tmp_path / "app" / "frontend"
    (fe / "src" / "services").mkdir(parents=True)
    (fe / "public" / "assets" / "real_videos").mkdir(parents=True)
    if stage_target:
        (fe / "public" / TARGET.lstrip("/")).write_bytes(b"\x00")
    body = "export const x = 1;\n"
    if table_target:
        body = ("const stagedVideoReplacements = {\n  '%s': '%s'\n};\n"
                "function normalizeVideo(i) {"
                " return {...i, video_url: stagedVideoReplacements[i.video_url] || i.video_url};"
                " }\n" % (MISSING, table_target))
    (fe / "src" / "services" / "api.js").write_text(body, encoding="utf-8")
    return tmp_path


def test_a_remapped_path_is_found_with_its_target(tmp_path):
    _tree(tmp_path, table_target=TARGET)
    assert remapped_seed_media_1203m3(tmp_path, [MISSING]) == {MISSING: TARGET}


def test_a_table_pointing_at_a_file_that_is_also_absent_is_not_a_remap(tmp_path):
    """The tight half: 'appears as a key' alone would overmatch (#1202w1)."""
    _tree(tmp_path, table_target=TARGET, stage_target=False)
    assert remapped_seed_media_1203m3(tmp_path, [MISSING]) == {}


def test_no_table_means_no_remap(tmp_path):
    _tree(tmp_path)
    assert remapped_seed_media_1203m3(tmp_path, [MISSING]) == {}


@pytest.mark.parametrize("args", [(None, None), ("/nonexistent/run", [MISSING]),
                                  (".", []), (".", None)])
def test_it_never_raises(args):
    assert remapped_seed_media_1203m3(*args) == {}


class _WH:
    def __init__(self):
        self.tasks = []

    def list_tasks(self):
        return []

    def create_task(self, **kw):
        self.tasks.append(kw)
        return "task_1"


class _Orch:
    def __init__(self, wh):
        self.hubs = type("H", (), {"workhub": wh})()


def _file_task(tmp_path, monkeypatch):
    monkeypatch.setattr(frontend_scaffold, "unstaged_seed_media_1202xn",
                        lambda _o: [MISSING], raising=True)
    wh = _WH()
    heal_pipeline._unstaged_seed_media_task_1202zf(_Orch(wh), tmp_path)
    assert len(wh.tasks) == 1, "the finding stopped reaching the lane"
    return wh.tasks[0]


def test_the_task_says_the_page_already_remapped_it(tmp_path, monkeypatch):
    """The caller, not the helper -- the text a lane actually receives."""
    _tree(tmp_path, table_target=TARGET)
    task = _file_task(tmp_path, monkeypatch)
    desc = task["description"]
    assert TARGET in desc, "the lane is not told what the page points at instead"
    assert "#1203m3" in desc and "may already play" in desc
    # never dropped, and never quietly downgraded
    assert MISSING in desc
    assert task["priority"] == "P1"


def test_a_genuine_404_is_reported_without_the_caveat(tmp_path, monkeypatch):
    """r181's shape: no remap, so nothing must soften the claim."""
    _tree(tmp_path)
    desc = _file_task(tmp_path, monkeypatch)["description"]
    assert MISSING in desc
    assert "#1203m3" not in desc and "may already play" not in desc
    assert "404" in desc or "presses play" in desc
