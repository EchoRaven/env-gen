"""#1202pv: an unresolved body placeholder resolves by the FIELD it fills and by a camelCase
variable, not to the chain's last unrelated id (tiktok-r126: sound_id="${soundId}" got a
video's id -> POST /api/videos 404 though the chain had just created a sound)."""
from env_generator.llm_generator.multi_agent.runtime.chain_executor import (
    _resolve_unresolved_dollar_vars as resolve,
)


def test_the_r126_step_gets_the_sound_the_chain_created():
    body = {"sound_id": "${soundId}", "caption": "c"}
    out = resolve(body, last_id=1, by_resource={"sound": 21, "video": 1})
    assert out["sound_id"] == 21


def test_the_field_names_the_resource_even_for_an_opaque_variable():
    out = resolve({"calendar_id": "${cal}"}, last_id=9, by_resource={"calendar": 4})
    assert out["calendar_id"] == 4


def test_created_prefix_is_folded():
    out = resolve({"x": "${createdSoundId}"}, last_id=1, by_resource={"sounds": 7})
    assert out["x"] == 7


def test_nothing_known_still_falls_back_to_last_id():
    assert resolve({"tag_id": "${tagId}"}, last_id=3, by_resource={"video": 1}) == {"tag_id": 3}


def test_the_snake_variable_rule_is_unchanged():
    assert resolve({"calendar_id": "${calendar_id}"}, last_id=5,
                   by_resource={"calendar": 2}) == {"calendar_id": 2}
