r"""#604: #302's context-reduction never fired for durable messages — read the POINTER.

`check_inbox` is the pipeline's largest token sink by a wide margin. Over the arc's 45 runs it
accounts for **68.9M of 108.6M tool-io tokens (63%)** — 3454 calls averaging **20k tokens**, a
median of **218 calls per run** (max 682). **69%** of reads lead with a message already
delivered (median re-delivery **3.09x**; r141 had ONE message head **150 of 210** reads).

#302 already built the fix — an already-read body returns a bounded preview plus its id — and its
own note named the stakes: *"r82: ~350KB of read bodies per inbox per call — the #1 token sink"*.
It could never fire for a durable message:

    list_inbox() returns {**event, "inbox": item}      <- the read flag lives on `item`
    the durable branch read  event.get("read")         <- events have NO top-level read key
                                                          (12910 of 12910 stored events)

So `_was_read` was always False on exactly the messages that are never cleared — every durable
event is stamped `persist: True` right there — while **81%** of the arc's 33130 inbox pointers
are in fact marked read. The state to act on was present the whole time, one level down.
"""
import inspect

import pytest

from env_generator.llm_generator.tools import communication_tools as ct


@pytest.fixture(scope="module")
def src():
    cls = next(c for n, c in vars(ct).items()
               if inspect.isclass(c) and getattr(c, "NAME", "") == "check_inbox")
    return inspect.getsource(cls)


def test_the_read_flag_comes_off_the_inbox_POINTER(src):
    assert 'bool((event.get("inbox") or {}).get("read")' in src


def test_the_old_event_level_read_is_kept_only_as_a_fallback(src):
    """Harmless if a future list_inbox flattens the pointer onto the event."""
    i = src.index('(event.get("inbox") or {}).get("read")')
    assert 'or event.get("read")' in src[i:i + 120]


def test_the_preview_branch_is_what_this_unblocks(src):
    assert '_was_read' in src
    assert 'is_preview = bool(msg.get("_was_read"))' in src


def test_an_unread_body_is_still_delivered_WHOLE(src):
    """#274/#291: a task_ready contract must never be clipped while it is unread."""
    i = src.index("is_preview =")
    window = src[i:i + 700]
    assert "else:" in window and "content = body" in window


def test_a_small_read_body_is_left_whole(src):
    """Nothing to save, and clipping it would add the preview banner for no gain."""
    i = src.index("is_preview =")
    assert "len(body) > _INBOX_PREVIEW_LEN" in src[i:i + 160]


def test_the_preview_says_how_to_get_the_full_body_back(src):
    i = src.index("already read.")
    window = src[i:i + 260]
    assert "search_messages" in window and "eventhub_get_thread" in window


def test_durable_events_are_still_marked_persist(src):
    """They are never cleared — which is exactly why the preview matters for them."""
    i = src.index('"eventhub": True')
    assert '"persist": True' in src[max(0, i - 400):i]


def test_unread_only_callers_are_unaffected(src):
    """They never reach the preview branch — the docstring's own guarantee."""
    assert "unread_only=True callers never hit the preview branch" in src


def test_the_measurement_that_justifies_it_is_recorded(src):
    assert "68.9M of 108.6M" in src and "12910 of 12910" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
