r"""#1202sr: 22 P0s on one endpoint, all with the same title.

The breaking-change task was titled `Fix breaking change in {endpoint}` and nothing else, so
every finding on one endpoint produced an identical row. Measured across the 36 runs since
`#1202gz`: 270 of 473 titles (57%) cover MORE THAN ONE distinct change, and tiktok-r120's
`Fix breaking change in GET /api/videos` covers 22 of them.

A lane looking at its P0 queue sees 22 identical lines. It cannot tell which it has already
fixed, which to take first, or whether two of them are the same work — which is the
category-without-the-instance shape that `#1017`, `#982` and `#1178` each removed from a
different message, and that my own corpus scan fell for: counting those titles as "verbatim
duplicates" until the payloads showed they were different findings.

`#1202gz` is right to file them separately; they just have to be tellable apart once filed.
Replaying every real payload in those 36 runs through the new title: 271 ambiguous titles
become 41, a drop of 85%.

The prefix is deliberately unchanged. `_relax` (registryhub, the "who was told auth was
added" lookup) matched the old title by EQUALITY, and is switched to a prefix match here —
that reader is the reason the endpoint has to stay at the front.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.registryhub import (
    _breaking_title_detail_1202sr as detail,
    _breaking_task_title_1202sr as title,
)


# --- it says what changed -------------------------------------------------------------

@pytest.mark.parametrize("breaking,expected", [
    ({"removed_response_fields": ["author", "user_id"]}, "removed author, user_id"),
    ({"type_changed_fields": ["sound"]}, "type changed sound"),
    ({"required_added_in_request": ["page"]}, "now requires page"),
    ({"auth_added": True}, "auth added"),
    ({"method_changed": True}, "method changed"),
])
def test_each_kind_of_change_is_named(breaking, expected):
    assert title("GET /api/videos", breaking) == "Fix breaking change in GET /api/videos: " + expected


def test_two_findings_on_one_endpoint_get_different_titles():
    """The whole point: r120 filed 22 of these under one line."""
    a = title("GET /api/videos", {"removed_response_fields": ["author"]})
    b = title("GET /api/videos", {"type_changed_fields": ["sound"]})
    assert a != b


def test_several_changes_are_all_named():
    out = title("GET /api/feed", {"removed_response_fields": ["a"], "auth_added": True})
    assert "removed a" in out and "auth added" in out


# --- and what it must not do ----------------------------------------------------------

def test_the_endpoint_stays_at_the_front():
    """`_relax` finds "who was told" by matching this prefix; moving the endpoint breaks it."""
    for breaking in ({"type_changed_fields": ["x"]}, {}, {"is_breaking": True}):
        assert title("GET /api/videos", breaking).startswith(
            "Fix breaking change in GET /api/videos")


def test_a_payload_with_nothing_nameable_keeps_the_bare_title():
    assert title("GET /api/videos", {"is_breaking": True}) == "Fix breaking change in GET /api/videos"
    assert title("GET /api/videos", {}) == "Fix breaking change in GET /api/videos"


def test_a_long_field_list_is_capped():
    out = title("GET /api/videos", {"removed_response_fields": [f"f{i}" for i in range(20)]})
    assert len(out) < 130 and out.startswith("Fix breaking change in GET /api/videos: removed ")


def test_malformed_payloads_never_raise():
    for bad in (None, "x", 42, [], {"removed_response_fields": None}):
        assert detail(bad) == "" or isinstance(detail(bad), str)
        assert title("GET /x", bad).startswith("Fix breaking change in GET /x")


# --- the reader that was keyed on the old title ---------------------------------------

def test_the_relax_lookup_matches_by_prefix_now():
    """Equality against the old title finds nothing once the detail is appended, and the
    "endpoint is public again" undo message would then silently reach no one."""
    import inspect

    from env_generator.llm_generator.multi_agent.runtime import registryhub

    src = inspect.getsource(registryhub)
    assert 't.get("title") == f"Fix breaking change in {endpoint_id}"' not in src, \
        "the relax lookup still matches the title by equality"
    assert 'startswith(' in src and 'Fix breaking change in {endpoint_id}' in src, \
        "the relax lookup no longer looks for this title at all"


def test_the_creation_site_uses_the_new_title():
    import inspect

    from env_generator.llm_generator.multi_agent.runtime import registryhub

    src = inspect.getsource(registryhub)
    assert "title=_breaking_task_title_1202sr(endpoint_id, breaking)" in src
    assert 'title=f"Fix breaking change in {endpoint_id}"' not in src
