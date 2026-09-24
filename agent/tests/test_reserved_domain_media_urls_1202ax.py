r"""#1202ax: a seeded media URL on a reserved domain is a guaranteed broken image.

RFC 2606 reserves example.com/.org/.net so they never serve real content. A seeded
`video_url`/`image_url` pointing there is not a placeholder that might resolve later —
it is a 404 every time, and the visual judge scores it as a broken render.

#1202j already refuses a LOCAL asset path that exists nowhere in the tree; an external
URL walks past that check because there is no local path to miss. Measured: 20 of 119
corpus runs with a delivered app ship at least one. Three hand-checked —
`https://example.com/ferry.jpg` (googlemaps), `https://example.com/article`
(instagram), and `https://example.com/avatar{i}.jpg`, an unformatted f-string that
reached the data as literal text.

An e-mail address is NOT this defect: `testuser@example.com` is the correct thing to
use for a probe account, which is why the pattern requires a scheme and a path.
"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent / "env_generator" / "llm_generator"))

from multi_agent.runtime.backend_audit import (  # noqa: E402
    placeholder_media_urls_1202ax)


class ReservedDomainMediaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="ax1202_"))
        self.be = self.root / "app" / "backend"
        self.be.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_a_seeded_image_url_is_reported(self):
        (self.be / "seed_data.json").write_text(json.dumps(
            {"titles": [{"id": 1, "image_url": "https://example.com/ferry.jpg"}]}))
        found = placeholder_media_urls_1202ax(self.root)
        self.assertEqual(len(found), 1)
        self.assertIn("ferry.jpg", found[0])

    def test_lane_authored_routes_are_scanned_too(self):
        """The case that started this: netflix-r32's games backfill inserts rows whose
        video_url is on example.com, and scanning only the seed files reported it clean."""
        (self.be / "custom_routes.py").write_text(
            'Title(id=1001, video_url="https://example.com/games/puzzle")\n')
        found = placeholder_media_urls_1202ax(self.root)
        self.assertEqual(len(found), 1)
        self.assertIn("custom_routes.py", found[0])

    def test_a_probe_email_is_not_a_finding(self):
        """Requiring a scheme and a path is what keeps test accounts out of this."""
        (self.be / "seed_data.json").write_text(json.dumps(
            {"users": [{"email": "testuser_probe@example.com"}]}))
        self.assertEqual(placeholder_media_urls_1202ax(self.root), [])

    def test_a_real_cdn_is_not_a_finding(self):
        """sample-videos.com is a REAL host — I have mis-flagged it before, so pin it."""
        (self.be / "seed_data.json").write_text(json.dumps(
            {"titles": [{"video_url": "https://sample-videos.com/video.mp4"}]}))
        self.assertEqual(placeholder_media_urls_1202ax(self.root), [])

    def test_a_clean_project_reports_nothing(self):
        (self.be / "seed_data.json").write_text(json.dumps(
            {"titles": [{"image_url": "/assets/posters/ferry.jpg"}]}))
        self.assertEqual(placeholder_media_urls_1202ax(self.root), [])

    def test_a_missing_backend_is_not_an_error(self):
        self.assertEqual(placeholder_media_urls_1202ax(self.root / "nope"), [])


if __name__ == "__main__":
    unittest.main()
