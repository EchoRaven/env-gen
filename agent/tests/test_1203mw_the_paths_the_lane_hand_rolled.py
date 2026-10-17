r"""#1203mw: the check for missing media read two seed filenames; the lane writes the paths
into custom_routes.py.

`unstaged_seed_media_1202xn` scans `seed_dataset.json` and `seed_data.json`, and
`stage_missing_seed_photos` -- which guarantees the IMAGES those two files reference -- scans
the same two. The lane hand-rolls `custom_routes.py` and returns asset paths straight out of
it, and neither check has ever looked there.

MEASURED over the 31 modern runs that have a `public/` tree: 12 ship a backend reference to a
file that is not in the delivered tree, 78 references in all, and **52 of those (67%) are in
`custom_routes.py`**. Six runs report ZERO while shipping between 4 and 12:

    tiktok-web-r169  12   tiktok-web-r183  12   tiktok-web-r186   9
    tiktok-web-r191   6   tiktok-web-r180   5   tiktok-web-r179   4

Split by kind: 26 videos in a seed JSON (seen today), 14 videos in `custom_routes.py` (35% of
the missing videos, unseen), and 38 images -- every one of them in `custom_routes.py` and
**none in a seed JSON**, which is why the image guarantee looked intact: it holds exactly
where it looks.

Not a false alarm, checked three ways: r169's `real_thumbnails/` directory does not exist
anywhere in its tree; `remapped_seed_media_1203m3` returns {} for all four runs spot-checked,
so no page rewrites them (#1203m3's lesson -- a regex hit is not a request); and the files are
absent from `public/`, which is the only root an absolute `/assets/...` URL is served from.

Reported, not placeholdered. #1202xn already refused to synthesise a stand-in video and said
why; a grey square where the lane invented `real_thumbnails/bts-dance-practice.jpg` -- while
the real thumbnail is staged under its own name -- hides the mismatch instead of naming it.
"""
import unittest
from pathlib import Path
import tempfile

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    unstaged_seed_media_1202xn as unstaged,
)


def _run(tmp, *, seed_json=None, custom_routes=None, staged=()):
    be = tmp / "app" / "backend"
    pub = tmp / "app" / "frontend" / "public" / "assets"
    be.mkdir(parents=True, exist_ok=True)
    pub.mkdir(parents=True, exist_ok=True)
    if seed_json is not None:
        (be / "seed_data.json").write_text(seed_json)
    if custom_routes is not None:
        (be / "custom_routes.py").write_text(custom_routes)
    for rel in staged:
        p = pub / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    return tmp


class _Tmp(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.tmp = Path(self._d.name)
        self.addCleanup(self._d.cleanup)


class TheHandRolledRouteIsSeen(_Tmp):
    def test_r169s_missing_thumbnail_is_reported(self):
        _run(self.tmp, custom_routes='THUMB = "/assets/real_thumbnails/bts-dance-practice.jpg"')
        out = unstaged(self.tmp)
        self.assertEqual(len(out), 1)
        self.assertIn("/assets/real_thumbnails/bts-dance-practice.jpg", out[0])

    def test_a_video_in_custom_routes_is_reported(self):
        """14 of the 40 missing videos corpus-wide, invisible before this."""
        _run(self.tmp, custom_routes='V = "/assets/real_videos/khaby-bottle-cap.mp4"')
        self.assertEqual(len(unstaged(self.tmp)), 1)

    def test_any_backend_module_counts_not_just_custom_routes(self):
        be = self.tmp / "app" / "backend"
        _run(self.tmp)
        (be / "seed_data.py").write_text('A = "/assets/real_avatars/mayarios.jpg"')
        self.assertEqual(len(unstaged(self.tmp)), 1)

    def test_a_staged_file_is_not_reported(self):
        _run(self.tmp, custom_routes='V = "/assets/real_videos/ok.mp4"',
             staged=("real_videos/ok.mp4",))
        self.assertEqual(unstaged(self.tmp), [])

    def test_the_same_path_in_two_places_is_reported_once(self):
        _run(self.tmp,
             seed_json='{"video_url": "/assets/real_videos/x.mp4"}',
             custom_routes='V = "/assets/real_videos/x.mp4"')
        self.assertEqual(len(unstaged(self.tmp)), 1)


class TheOldScopeStillWorks(_Tmp):
    def test_a_seed_json_video_is_still_reported(self):
        _run(self.tmp, seed_json='{"video_url": "/assets/real_videos/gone.mp4"}')
        self.assertEqual(len(unstaged(self.tmp)), 1)

    def test_a_seed_json_image_is_still_left_to_the_stager(self):
        """`stage_missing_seed_photos` places a file for every image the seed JSON names, so
        reporting those here would report what the next step fixes. 0 of the 38 missing
        images corpus-wide are in a seed JSON."""
        _run(self.tmp, seed_json='{"photo_url": "/assets/photos/p.jpg"}')
        self.assertEqual(unstaged(self.tmp), [])

    def test_framework_owned_prefixes_are_skipped_everywhere(self):
        _run(self.tmp, custom_routes='I = "/assets/icons/x.svg"\nP = "/assets/placeholders/p.jpg"')
        self.assertEqual(unstaged(self.tmp), [])

    def test_pycache_is_not_scanned(self):
        be = self.tmp / "app" / "backend" / "__pycache__"
        _run(self.tmp)
        be.mkdir(parents=True, exist_ok=True)
        (be / "stale.py").write_text('OLD = "/assets/real_videos/deleted.mp4"')
        self.assertEqual(unstaged(self.tmp), [])


class ItStillNamesTheCause(_Tmp):
    def test_not_staged_is_still_spelled_out(self):
        _run(self.tmp, custom_routes='V = "/assets/real_videos/x.mp4"')
        self.assertTrue(unstaged(self.tmp)[0].endswith("(not staged)"))

    def test_a_dockerignored_file_keeps_its_own_cause(self):
        """#1202xo: on disk and excluded from the image is a different owner."""
        _run(self.tmp, custom_routes='V = "/assets/real_videos/big.mp4"',
             staged=("real_videos/big.mp4",))
        (self.tmp / "app" / "frontend" / ".dockerignore").write_text(
            "public/assets/real_videos/*.mp4\n")
        out = unstaged(self.tmp)
        self.assertEqual(len(out), 1)
        self.assertIn(".dockerignore", out[0])


class TheConsumersSayTheTruthForAnImageToo(unittest.TestCase):
    def _src(self, mod):
        import inspect
        return inspect.getsource(mod)

    def test_the_warning_no_longer_promises_a_thumbnail(self):
        from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold
        src = self._src(frontend_scaffold)
        self.assertNotIn("those cards render a thumbnail and fail on play", src)

    def test_the_warning_covers_both_kinds(self):
        from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold
        import ast
        tree = ast.parse(self._src(frontend_scaffold))
        texts = [a.value for n in ast.walk(tree) if isinstance(n, ast.Call)
                 for a in n.args if isinstance(a, ast.Constant)
                 and isinstance(a.value, str) and "#1202xn %d" in a.value]
        self.assertTrue(texts, "the #1202xn warning literal is gone")
        self.assertIn("broken glyph", texts[0])
        self.assertIn("plays nothing", texts[0])


class TheDedupeIsKeyedOnTheMarkerNotTheWording(unittest.TestCase):
    """It matched startswith(base); rewriting the sentence would have cloned the task."""

    def _keys(self):
        import ast
        import inspect
        from env_generator.llm_generator.multi_agent.runtime import heal_pipeline
        tree = ast.parse(inspect.getsource(heal_pipeline))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                    getattr(t, "id", "") == "_keys_1203mw" for t in node.targets):
                return [e.value for e in node.value.elts]
        return None

    def test_the_ticket_marker_is_a_key(self):
        self.assertIn("#1202zf", self._keys() or [])

    def test_the_pre_change_wording_is_still_a_key(self):
        self.assertIn("Seeded media missing at delivery", self._keys() or [])


class _WH:
    def __init__(self):
        self.created = []

    def list_tasks(self):
        return []

    def create_task(self, **kw):
        self.created.append(kw)
        return "t1"


class _Hubs:
    def __init__(self, wh):
        self.workhub = wh


class _Orch:
    def __init__(self, wh):
        self.hubs = _Hubs(wh)


class TheWholeChainCarriesIt(_Tmp):
    """Composition, not two green halves: the REAL detector feeding the REAL task filer.

    Every existing test of the filing site monkeypatches `unstaged_seed_media_1202xn`, so a
    path this ticket newly finds could have stopped at the detector and nothing would be red.
    """

    def test_a_custom_routes_path_reaches_the_frontend_task(self):
        from env_generator.llm_generator.multi_agent.runtime import heal_pipeline as HP
        _run(self.tmp,
             custom_routes='THUMB = "/assets/real_thumbnails/bts-dance-practice.jpg"')
        wh = _WH()
        HP._unstaged_seed_media_task_1202zf(_Orch(wh), self.tmp)
        self.assertEqual(len(wh.created), 1, wh.created)
        self.assertIn("real_thumbnails/bts-dance-practice.jpg",
                      wh.created[0]["description"])
        self.assertEqual(wh.created[0]["assignee"], "frontend")

    def test_a_tree_with_nothing_missing_files_nothing(self):
        from env_generator.llm_generator.multi_agent.runtime import heal_pipeline as HP
        _run(self.tmp, custom_routes='V = "/assets/real_videos/ok.mp4"',
             staged=("real_videos/ok.mp4",))
        wh = _WH()
        HP._unstaged_seed_media_task_1202zf(_Orch(wh), self.tmp)
        self.assertEqual(wh.created, [])


if __name__ == "__main__":
    unittest.main()
