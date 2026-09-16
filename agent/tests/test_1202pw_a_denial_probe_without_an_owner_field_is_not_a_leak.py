"""#1202pw: a denial probe that succeeds is a leak only when it named an OWNER field.
tiktok-r126 called a notification carrying its own title and public video/comment ids
"BOUNDARY CROSSED - a data-isolation hole" while the row was stored under the caller."""
import json

from env_generator.llm_generator.multi_agent.runtime.chain_executor import (
    _denial_scope_verdict_663 as verdict,
)

R126_SENT = {"type": "comment", "title": "Verifier cross-user denial", "body": "should be denied",
             "video_id": "44", "comment_id": "18", "is_read": False}
R126_GOT = json.dumps({"item": {"id": 11, "user_id": 32, "actor_id": None, "type": "comment",
                                "title": "Verifier cross-user denial", "body": "should be denied",
                                "video_id": 44, "comment_id": 18, "is_read": False}})


def test_the_r126_probe_is_not_called_a_leak():
    v = verdict(R126_SENT, R126_GOT)
    assert "BOUNDARY CROSSED" not in v
    assert v.startswith("NOT A BOUNDARY PROBE")
    assert "user_id=32" in v


def test_an_echoed_foreign_owner_id_is_still_a_leak():
    sent = dict(R126_SENT, user_id="7")
    got = json.dumps({"item": {"id": 12, "user_id": 7, "title": "x"}})
    v = verdict(sent, got)
    assert v.startswith("BOUNDARY CROSSED") and "user_id='7'" in v
    assert "title" not in v


def test_a_substituted_owner_id_is_a_wrong_status():
    got = json.dumps({"item": {"id": 13, "user_id": 32, "title": "x"}})
    assert verdict({"user_id": "7", "title": "x"}, got).startswith("no data crossed")
