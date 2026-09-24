"""#279 — the For-You feed is a PUBLIC read; only following/friends are personalised.

r62 (opus-4.7, all fixes): the cleanest run yet — backend healthy, run_validation 13/13,
all of #270-#278 held with zero recurrence — but it stalled on ui_flow_failed for fyp_feed
and comments_panel. Root: GET /api/feed/foryou (auth_required unstated) was classified
auth-required by #271, which lumped the For-You feed in with following/friends. The browser
walk then navigated the feed anonymously, hit 401, and recorded a flow failure on a working
app.

This is an over-narrowing #271 introduced. following / friends ARE personalised (scoped to a
specific user's graph → need auth). But the For-You / FYP feed is the app's PUBLIC recommended
stream — real TikTok serves it logged-out (anonymous browsing is the product; the login wall
appears only on interaction). Requiring auth on it is both wrong for the domain and the thing
that made the anonymous flow walk fail.

Fix: drop for-you / foryou from the self/personalised markers so an UNSTATED for-you feed
defaults to public, while following / friends keep requiring auth. An explicit auth_required
in the contract still wins either way.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from env_generator.llm_generator.multi_agent.runtime.route_projector import (  # noqa: E402
    resolve_endpoint_auth,
)


def test_r62_regression_foryou_feed_is_public_when_unstated():
    for path in ("/api/feed/for-you", "/api/feed/foryou", "/api/feed/fyp"):
        assert resolve_endpoint_auth("GET", path, {"auth_required": None}) is False, path


def test_following_and_friends_still_require_auth():
    """The genuinely personalised feeds keep their auth default — #271 stays intact."""
    for path in ("/api/feed/following", "/api/feed/friends"):
        assert resolve_endpoint_auth("GET", path, {"auth_required": None}) is True, path


def test_explicit_auth_on_foryou_is_honoured():
    """A contract that deliberately gates the FYP behind auth still wins."""
    assert resolve_endpoint_auth("GET", "/api/feed/foryou", {"auth_required": True}) is True


def test_other_self_reads_unchanged():
    for path in ("/api/me", "/api/notifications", "/api/inbox"):
        assert resolve_endpoint_auth("GET", path, {"auth_required": None}) is True, path


def test_a_write_to_the_feed_still_needs_auth():
    """Posting/refreshing is a mutation regardless of which feed."""
    assert resolve_endpoint_auth("POST", "/api/feed/foryou", {}) is True
