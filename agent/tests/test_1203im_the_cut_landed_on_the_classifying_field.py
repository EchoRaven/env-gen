"""#1203im — `str(e)[:200]` split `insufficient_quota` in half, 271 times.

Measured over r183-r186: every one of the 271 logged 429s is EXACTLY 200 characters and
every one stops at

    ... 'type': 'insufficient_quo

which cuts `insufficient_quota` — the single token that distinguishes throttling from an
exhausted balance. Both #1159 ("ask what the 429 says before deciding it is transient") and
#1174 (the grace window) turn on that distinction. `_is_terminal_llm_error` reads the
exception OBJECT, so the decision was never wrong; what was wrong is the log every human and
every later analysis reads.

I was the measurable victim. Grepping these logs for `insufficient_quota` returned 0, so I
concluded the framework was retrying an exhausted balance as a throttle, and spent a whole
investigation before finding #1159/#1174 already handle it.

The 400s were never affected (193-221 chars, `code: 'image_parse_error'` intact), which is
why this never surfaced there.
"""
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _AGENT)

from utils.llm import _error_msg_1203im as msg  # noqa: E402

# verbatim shape of the 429 this exists for, reconstructed from the logged prefix
QUOTA_429 = (
    "Error code: 429 - {'error': {'message': 'You have no credits remaining. Add credits "
    "to continue using the API at https://platform.openai.com/settings/organization/"
    "billing/.', 'type': 'insufficient_quota', 'code': None, 'param': None}}")

IMAGE_400 = (
    "Error code: 400 - {'error': {'message': 'You uploaded an unsupported image. Please "
    "make sure your image is valid.', 'type': 'invalid_request_error', 'param': None, "
    "'code': 'image_parse_error'}}")


def test_the_quota_token_survives_the_cut():
    """★ THE DEFECT. Before this, the 200-char cut landed mid-token."""
    out = msg(QUOTA_429)
    assert "insufficient_quota" in out, (
        "the token that says throttle-vs-exhausted is still being cut: %r" % out[-60:])


def test_a_message_that_fits_is_returned_byte_for_byte():
    """#1202vx: the explanation must not spend the evidence budget. Nothing may get noisier
    for the messages that were already complete — which is every 400 in the corpus."""
    short = "Error code: 500 - server blew up"
    assert msg(short) == short
    # the real 400 is 193 chars and already carries its code
    assert len(IMAGE_400) <= 200
    assert msg(IMAGE_400) == IMAGE_400


def test_only_what_the_cut_removed_is_appended():
    """`invalid_request_error` is inside the first 200 chars of the 400, so it must not be
    repeated. Appending fields that already survived would be pure noise."""
    out = msg(QUOTA_429)
    # `type` was cut, so it comes back
    assert "type=insufficient_quota" in out
    # and it is appended ONCE
    assert out.count("insufficient_quota") == 1, out[-80:]


def test_a_field_that_survived_the_cut_is_not_repeated():
    """★ THE GUARD M2 needed. Removing the "already survived" check stayed green, because
    every other case here has its field BEYOND the cut. This one puts `type` inside the first
    200 characters of an over-long message: appending it again would be pure noise, which is
    the #1202vx failure mode this helper is supposed to avoid."""
    early = ("Error code: 400 - {'error': {'type': 'invalid_request_error', 'message': '%s'}}"
             % ("z" * 300))
    assert len(early) > 200
    assert "'type': 'invalid_request_error'" in early[:200], "fixture does not test the case"
    out = msg(early)
    assert out.count("invalid_request_error") == 1, (
        "a field that already survived the cut was appended again: %r" % out[-70:])
    assert "type=" not in out


def test_the_head_is_preserved_exactly():
    """The human-readable message must still lead; this appends, never replaces."""
    out = msg(QUOTA_429)
    assert out.startswith(QUOTA_429[:200])
    assert "You have no credits remaining" in out


def test_a_code_past_the_cut_is_kept_too():
    """Not quota-specific: any provider field that classifies the error."""
    long_400 = ("Error code: 400 - {'error': {'message': '%s', 'code': 'context_length_"
                "exceeded'}}" % ("x" * 220))
    out = msg(long_400)
    assert "code=context_length_exceeded" in out


def test_no_classifying_field_means_a_plain_cut():
    """Nothing to rescue → behave exactly as before, with no decoration."""
    plain = "y" * 400
    assert msg(plain) == "y" * 200


def test_hostile_inputs_do_not_raise():
    class _Boom:
        def __str__(self):
            raise RuntimeError("no str for you")
    assert msg(_Boom()) == ""
    assert msg(None) == "None"


def test_the_call_site_uses_it():
    """★ Pinned over the AST: the helper exists to replace `str(e)[:200]` at the retry
    site. A helper nobody calls is the shape this session kept finding."""
    import ast
    import pathlib
    src = pathlib.Path(_AGENT, "utils/llm.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    assigns = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == "error_msg" for t in n.targets)]
    assert assigns, "error_msg is no longer assigned"
    seg = " ".join(ast.get_source_segment(src, a.value) or "" for a in assigns)
    assert "_error_msg_1203im" in seg, "the retry site still cuts the body blindly"
    assert "str(e)[:200]" not in seg, "the blind cut came back"
