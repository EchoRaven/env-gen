r"""#1202zf: seeded media missing AT DELIVERY reaches no lane.

`unstaged_seed_media_1202xn` finds it and `record_unstaged_seed_media_1202xn` lands it in
`logs/unstaged_seed_media_1202xn.jsonl`. The harm is a card that renders its thumbnail — which
IS an image and therefore IS staged — and 404s the moment a viewer presses play.

★ WHAT THE CORPUS SHOWS IS WORSE THAN SILENCE. The ticket token appears in ZERO hub files
across every run, and TWICE an agent paid to rediscover the same fact from a browser 404:
r121's debugger wrote the root cause itself ("synthetic local media paths … that are not staged
frontend assets; feed responses returned them verbatim, causing browser 404s") and r62's
verifier recorded "file not staged in frontend /assets/real_videos/ or missing from static
build" as a test result. The framework knew both answers before either agent started looking.

★ LATE, NOT WHERE THE DETECTOR ALREADY RUNS. The existing call is at SCAFFOLD time and most of
what it reports there is transient. Measured on r139: 36 ledger lines carrying 35 videos
"excluded from the image by .dockerignore", 1260 entries — and the delivered tree is CLEAN,
because the framework's own baseline copy rewrote `.dockerignore` TEN SECONDS after the last
report (file mtime 00:14:57, last ledger line 00:14:47) and all 35 files are on disk. Reporting
a state the framework is about to repair is how a signal teaches its reader to skip it.

What survives to delivery is real: r140 shipped THREE seeded videos still absent from the
delivered tree, beside 35 that ARE staged. Same shape in r124 (2), r129 (3), r135 (1).
"""
import ast
import inspect
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

import multi_agent.runtime.frontend_scaffold as FS  # noqa: E402
import multi_agent.runtime.heal_pipeline as HP      # noqa: E402

_R140 = ["/assets/real_videos/jasonderulo__7658062942529097015.mp4 (not staged)",
         "/assets/real_videos/khaby.lame__7655124220186492182.mp4 (not staged)",
         "/assets/real_videos/gordonramsayofficial__7659188408110628126.mp4 (not staged)"]


class _WH:
    def __init__(self, existing=None):
        self.tasks = list(existing or [])
        self.created = []

    def list_tasks(self):
        return self.tasks

    def create_task(self, **kw):
        # Faithful: a real WorkHub's `list_tasks` returns what `create_task` stored, so the
        # dedupe can see its own work.
        self.created.append(kw)
        rec = {"id": "t%d" % len(self.created), "status": "pending", **kw}
        self.tasks.append(rec)
        return rec


class _Orch:
    def __init__(self, wh):
        class _H:
            workhub = wh
        self.hubs = _H()


def _run(monkeypatch, tmp_path, missing, wh=None, staged=0):
    monkeypatch.setattr(FS, "unstaged_seed_media_1202xn", lambda *a, **k: list(missing))
    if staged:
        d = tmp_path / "app" / "frontend" / "public" / "assets" / "real_videos"
        d.mkdir(parents=True, exist_ok=True)
        for i in range(staged):
            (d / ("v%d.mp4" % i)).write_text("x", encoding="utf-8")
    wh = _WH() if wh is None else wh
    HP._unstaged_seed_media_task_1202zf(_Orch(wh), tmp_path)
    return wh


def test_a_task_is_filed_for_the_frontend(tmp_path, monkeypatch):
    wh = _run(monkeypatch, tmp_path, _R140)
    assert len(wh.created) == 1, wh.created
    assert wh.created[0]["assignee"] == "frontend"
    assert wh.created[0]["priority"] == "P1", "a task, not a blocker"
    assert "(3)" in wh.created[0]["title"]


def test_nothing_missing_files_nothing(tmp_path, monkeypatch):
    wh = _run(monkeypatch, tmp_path, [])
    assert wh.created == []


def test_the_task_names_every_file_it_can(tmp_path, monkeypatch):
    """#983: a count cannot be acted on."""
    d = _run(monkeypatch, tmp_path, _R140).created[0]["description"]
    for m in _R140:
        assert m.split(" ")[0] in d, d


def test_a_long_list_is_capped_but_says_so(tmp_path, monkeypatch):
    many = ["/assets/real_videos/v%d.mp4 (not staged)" % i for i in range(20)]
    d = _run(monkeypatch, tmp_path, many).created[0]["description"]
    assert "and 8 more" in d, d


def test_the_task_says_how_many_alternatives_are_staged(tmp_path, monkeypatch):
    """★ The lane can only act if repointing is possible, and whether it is depends on a number
    the lane cannot see from the task otherwise. r140 had 35 staged beside its 3 missing."""
    d = _run(monkeypatch, tmp_path, _R140, staged=35).created[0]["description"]
    assert "35 playable media file(s) ARE staged" in d, d


def test_the_task_says_to_fix_the_seed_row_not_the_page(tmp_path, monkeypatch):
    """The page is innocent — `thumbnail_url` renders fine. A lane sent to the page edits the
    wrong file."""
    d = _run(monkeypatch, tmp_path, _R140).created[0]["description"]
    assert "Fix the SEED ROW, not the page" in d, d


def test_the_task_forbids_a_placeholder(tmp_path, monkeypatch):
    """#1202xn's own reasoning, kept: the framework stages REAL media and a grey stand-in is
    worse than a named gap. It is also the user's standing rule about fallbacks that mask."""
    d = _run(monkeypatch, tmp_path, _R140).created[0]["description"]
    assert "Do NOT add a placeholder" in d, d


def test_the_dockerignore_cause_gets_its_own_instruction(tmp_path, monkeypatch):
    """★ Two causes with different repairs. `not staged` means the file is nowhere; `excluded
    from the image by .dockerignore` means it is on disk and the lane's own pattern keeps it
    out — and if a large file broke the build, the FILE is what to replace."""
    d = _run(monkeypatch, tmp_path,
             ["/assets/real_videos/a.mp4 (excluded from the image by .dockerignore)"]
             ).created[0]["description"]
    assert ".dockerignore" in d and "replace the FILE" in d, d


def test_an_open_task_is_not_cloned(tmp_path, monkeypatch):
    wh = _WH([{"title": "Seeded media missing at delivery — cards render a thumbnail and 404 "
                        "on play (3)", "status": "in_progress"}])
    _run(monkeypatch, tmp_path, _R140, wh=wh)
    assert wh.created == [], wh.created


def test_filing_twice_in_one_run_files_once(tmp_path, monkeypatch):
    """The post-merge site runs once or twice per milestone; the dedupe must see its own task."""
    wh = _WH()
    for _ in range(3):
        _run(monkeypatch, tmp_path, _R140, wh=wh)
    assert len(wh.created) == 1, wh.created


def test_a_completed_task_does_not_suppress_a_new_one(tmp_path, monkeypatch):
    wh = _WH([{"title": "Seeded media missing at delivery — cards render a thumbnail and 404 "
                        "on play (3)", "status": "completed"}])
    _run(monkeypatch, tmp_path, _R140, wh=wh)
    assert len(wh.created) == 1


def test_a_missing_workhub_is_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(FS, "unstaged_seed_media_1202xn", lambda *a, **k: list(_R140))

    class _NoHub:
        hubs = None
    HP._unstaged_seed_media_task_1202zf(_NoHub(), tmp_path)      # must not raise


def test_a_listing_fault_still_files(tmp_path, monkeypatch):
    class _Bad(_WH):
        def list_tasks(self):
            raise RuntimeError("hub down")
    wh = _Bad()
    _run(monkeypatch, tmp_path, _R140, wh=wh)
    assert len(wh.created) == 1, "a dedupe fault must not swallow the task"


def test_a_broken_detector_does_not_crash_the_heal_cycle(tmp_path, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("cannot read the seed")
    monkeypatch.setattr(FS, "unstaged_seed_media_1202xn", _boom)
    HP._unstaged_seed_media_task_1202zf(_Orch(_WH()), tmp_path)   # must not raise


def test_it_calls_the_existing_detector_rather_than_rescanning():
    """★ #1032: a second scan of the seed for media paths would be a second authority on which
    files are missing, and the two would disagree the first time one of them learned a new
    extension."""
    src = inspect.getsource(HP._unstaged_seed_media_task_1202zf)
    assert "unstaged_seed_media_1202xn" in src
    tree = ast.parse(src.lstrip())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            n = getattr(node.func, "attr", "") or getattr(node.func, "id", "")
            assert n not in ("finditer", "findall"), "the seed is being re-scanned here"


def test_the_caller_runs_at_the_late_site_and_is_not_behind_a_branch():
    """★ Three properties: called once, fed `out_dir`, and placed beside the other post-merge
    reporters — at SCAFFOLD time the same detector is mostly reporting states the framework is
    about to repair (r139: 1260 entries, delivered tree clean)."""
    tree = ast.parse(inspect.getsource(HP.HealPipeline).lstrip())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "_unstaged_seed_media_task_1202zf"]
    assert len(calls) == 1, "called %d times" % len(calls)
    assert any(getattr(a, "id", "") == "out_dir" for a in calls[0].args), ast.dump(calls[0])[:200]
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and any(c is calls[0] for c in ast.walk(node)):
            raise AssertionError("the call sits behind a branch: %s" % ast.dump(node.test)[:140])
