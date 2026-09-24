r"""#1202dh: #1202m addressed the backend and then wrote to the log.

#71 built a per-endpoint reject counter to break the verifier's retry loop; #664 found it
was in memory and persisted it. #1202m then diagnosed the remaining half correctly, in its
own words:

    this message reaches the VERIFIER, and it ends by telling it to ask the backend lane.
    Nothing tells the BACKEND. So the only party who can end the loop ... never hears that
    it is being asked for.
    ...
    All this does is put the request where the party who can answer it will see it.

What it actually does is `logging.getLogger(__name__).warning(...)`. Agents read an inbox;
nothing reads the framework's Python log. So the party who can answer still never hears,
and the counter keeps climbing — netflix-r42 logged 64 of these for one endpoint, and the
module's own note records the corpus: 514 rejections across 50 of 50 runs, r26 climbing
monotonically to 49 and never plateauing.

`EventHub.publish_api_requirement` is the channel this codebase already built for exactly
this — a typed requirement addressed to `recipients=["backend"]` — and `RegistryHub.__init__`
already accepts and stores an `eventhub`. The wiring existed; the call did not.

Deliberately unchanged (the contract #664/#71 and three tests defend): the rejection still
stands, the chain still covers what it covered, no task is filed, and the verifier's
guidance text is untouched. This only delivers the request to the one party able to act.

Published ONCE per endpoint, when the count first reaches 2 — the moment a reject becomes a
loop. A notification repeated 64 times is the bug being fixed, not a louder version of it.
"""
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime.registryhub import RegistryHub

_HALLUCINATED = [{"method": "PUT", "path": "/api/profiles/{id}", "body": {"name": "x"}}]


class _SpyHub:
    """Captures publish_api_requirement the way EventHub would receive it."""

    def __init__(self):
        self.published = []
        self.events = []

    def publish_api_requirement(self, **kwargs):
        self.published.append(kwargs)
        return {"event_id": "e1"}

    # register_endpoint publishes through this; it is not what this test is about.
    def publish_event(self, *args, **kwargs):
        self.events.append((args, kwargs))
        return {"event_id": "e0"}


def _hub(d, eventhub=None):
    rh = RegistryHub(Path(d), eventhub=eventhub)
    for m, p in (("POST", "/auth/register"), ("POST", "/auth/login"),
                 ("GET", "/api/profiles"), ("POST", "/api/profiles")):
        rh.register_endpoint(m, p, status="implemented")
    return rh


def test_one_reject_is_not_yet_a_loop(tmp_path):
    spy = _SpyHub()
    _hub(tmp_path, spy).register_verification_chain("c0", _HALLUCINATED)
    assert spy.published == []


def test_the_backend_is_told_when_the_reject_becomes_a_loop(tmp_path):
    spy = _SpyHub()
    for i in range(2):
        _hub(tmp_path, spy).register_verification_chain(f"c{i}", _HALLUCINATED)
    assert len(spy.published) == 1, spy.published
    shape = spy.published[0].get("needed_data_shape") or {}
    assert "profiles" in repr(shape), shape


def test_it_is_published_once_not_once_per_reject(tmp_path):
    """r42 logged this 64 times for one endpoint. A notification is not a nag."""
    spy = _SpyHub()
    for i in range(8):
        _hub(tmp_path, spy).register_verification_chain(f"c{i}", _HALLUCINATED)
    assert len(spy.published) == 1, spy.published


def test_a_hub_without_an_eventhub_still_rejects_and_does_not_raise(tmp_path):
    """Bootstrap and tests construct RegistryHub with no eventhub."""
    res = None
    for i in range(3):
        res = _hub(tmp_path, None).register_verification_chain(f"c{i}", _HALLUCINATED)
    assert "been rejected" in str((res or {}).get("error") or "")


def test_the_verifier_still_gets_its_escalation_text(tmp_path):
    """#71/#664's contract is untouched — silence toward one reader, not the other."""
    spy = _SpyHub()
    res = None
    for i in range(2):
        res = _hub(tmp_path, spy).register_verification_chain(f"c{i}", _HALLUCINATED)
    err = str((res or {}).get("error") or "")
    assert "been rejected" in err and "DROP those steps" in err, err


# --- the gap the live run exposed ---------------------------------------------------------
#
# `count == 2` was the wrong idempotency key. #664 PERSISTS the counter across processes, so
# on netflix-r44 `PUT /api/profiles/{}` was already at 17-19 from the first process; every
# later process only pushed it higher and the equality never held again. r44-resume2 logged
# `#1202m` twice and published ZERO api_requirement events.
#
# It matters more than a missed notification, because resume WIPES agent conversation context
# (measured: LLM `messages` restarts at 5 after a resume). The backend lane in a resumed run
# has no memory of ever being told, and under `== 2` it could never be told again.
#
# The key is "has this endpoint been announced yet", persisted — so a run whose counter passed
# 2 before this existed still gets exactly one announcement, and never a second.

def test_a_resumed_run_whose_counter_is_already_past_two_still_gets_told(tmp_path):
    """r44's shape: the counter arrives well past 2 with nothing ever announced."""
    spy = _SpyHub()
    for i in range(6):                      # drive the counter to 6
        _hub(tmp_path, None).register_verification_chain(f"c{i}", _HALLUCINATED)
    assert spy.published == []
    _hub(tmp_path, spy).register_verification_chain("c9", _HALLUCINATED)
    assert len(spy.published) == 1, spy.published


def test_it_is_still_only_ever_announced_once(tmp_path):
    spy = _SpyHub()
    for i in range(8):
        _hub(tmp_path, spy).register_verification_chain(f"c{i}", _HALLUCINATED)
    assert len(spy.published) == 1, spy.published


def test_the_marker_is_on_disk_where_the_counter_is(tmp_path):
    """#664's lesson: an in-memory marker resets, and 'once' becomes 'once per instance'."""
    spy = _SpyHub()
    for i in range(3):
        _hub(tmp_path, spy).register_verification_chain(f"c{i}", _HALLUCINATED)
    assert (Path(tmp_path) / "registryhub_chain_reject_announced_1202dh.json").is_file()


# --- #1202dz: the spy accepted a call the REAL EventHub rejects ---------------------------
#
# netflix-r45 logged 22 #1202m warnings and published ZERO api_requirement events. The
# announce-marker's .lock existed and its .json did not — the store was constructed, the
# publish never landed.
#
# `publish_api_requirement` publishes with `source_hub="eventhub"`, and eventhub's authorship
# gate is documented as "internal trampoline -> empty-caller fallthrough only"
# (PHASE_4_1C_PUBLISH_SENTINELS). Passing `caller="registryhub"` raised PermissionError, and
# the `except Exception: pass` around the block hid it for the whole run.
#
# The unit tests above could not catch it: `_SpyHub.publish_event(*args, **kwargs)` accepts
# any signature and enforces no gate. A double that is more permissive than the real
# collaborator tests the double. This one drives the REAL EventHub.

def test_it_publishes_through_the_real_eventhub(tmp_path):
    from env_generator.llm_generator.multi_agent.runtime.eventhub import EventHub
    ev = EventHub(Path(tmp_path))
    rh = RegistryHub(Path(tmp_path), eventhub=ev)
    for m, p in (("POST", "/auth/register"), ("POST", "/auth/login"),
                 ("GET", "/api/profiles"), ("POST", "/api/profiles")):
        rh.register_endpoint(m, p, status="implemented")
    for i in range(2):
        RegistryHub(Path(tmp_path), eventhub=ev).register_verification_chain(
            f"c{i}", _HALLUCINATED)

    events = ev.list_events_by_type("api_requirement") or []
    assert len(events) == 1, (
        "the real EventHub published %d api_requirement events — r45's shape was 0, hidden "
        "by a swallowed PermissionError" % len(events))
    assert "backend" in (events[0].get("recipients") or [])


def test_the_announce_marker_is_written_after_a_real_publish(tmp_path):
    from env_generator.llm_generator.multi_agent.runtime.eventhub import EventHub
    ev = EventHub(Path(tmp_path))
    rh = RegistryHub(Path(tmp_path), eventhub=ev)
    for m, p in (("GET", "/api/profiles"), ("POST", "/api/profiles")):
        rh.register_endpoint(m, p, status="implemented")
    for i in range(2):
        RegistryHub(Path(tmp_path), eventhub=ev).register_verification_chain(
            f"c{i}", _HALLUCINATED)
    assert (Path(tmp_path) / "registryhub_chain_reject_announced_1202dh.json").is_file(), (
        "r45 left only the .lock — the store was built and the publish never landed")
