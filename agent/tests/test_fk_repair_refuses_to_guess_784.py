r"""#784: the handler FK-alias repair must not pick an actor when the model has two.

Found by applying item 110's rule — *when a fix generalises by matching a SHAPE, the shape is
almost never the thing that makes it correct* — to every shape-matching site in the runtime.

`repair_handler_fk_aliases` rewrites `<Model>.<alias>` to "the model's real owner FK" when the
alias is not a column. Its own docstring states the precondition:

    "...but the model has a **single** owner FK, rewrite it to that FK"

**The code never checked that.** `_owner_fk` returns the FIRST match in `_OWNER_FK_NAMES` order,
so on a model carrying two of them it does not resolve the ambiguity — it hides it. And
`_OWNER_FK_NAMES` contains directional halves (`sender_id`, `follower_id`, `from_user_id`), so on
`messages(sender_id, recipient_id)` a broken `Message.user_id` inside an INBOX handler is
rewritten to `sender_id`: the endpoint then returns the caller's SENT mail, 200 OK, and no chain
step notices. That is a wrong-owner read introduced BY a repair.

Scope, honestly stated:
  * the repair has **never fired** in this corpus — no run log contains its message. It was built
    for an instagram run and netflix does not hit it. The hazard is latent, not active.
  * 48 of 1671 corpus tables (2%) carry two owner-ish columns, and **all of them are
    `user_id` + `profile_id`** on the per-profile private tables. No directional pairs exist here,
    so the sender/recipient case cannot be demonstrated on real data — only constructed.

So this is not a fix for an observed failure. It is the code being made to honour the contract its
own docstring already claims, on a surface where the session has twice found that owner-scoping
changes are safety changes (#568, #569). Declining leaves a loud AttributeError 500 rather than a
silent wrong-owner query, and now says so in the log.
"""
import inspect
import textwrap

import pytest

from env_generator.llm_generator.multi_agent.runtime import handler_fk_repair as hfr
from env_generator.llm_generator.multi_agent.runtime import heal_pipeline


# Shaped like real generated models, which DECLARE their foreign keys — the first version of
# this fixture used bare `Column(Integer)`, and with no FK targets to read the guard could only
# fall back to name matching, which is the very thing #784 is about.
_MODELS = '''
from sqlalchemy import Column, Integer, String, ForeignKey
from .base import Base

class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    caption = Column(String)

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    body = Column(String)
'''


def _backend(tmp_path, main_src):
    b = tmp_path / "backend"
    b.mkdir()
    (b / "models.py").write_text(textwrap.dedent(_MODELS), encoding="utf-8")
    (b / "main.py").write_text(textwrap.dedent(main_src), encoding="utf-8")
    return b


# --- the case the repair exists for still works ----------------------------------------------------

def test_the_single_owner_case_is_still_repaired(tmp_path):
    """instagram MM run #9: Post's owner is `author_id`, the handler queried `Post.user_id`."""
    b = _backend(tmp_path, "q = db.query(Post).filter(Post.user_id == me.id).all()\n")
    res = hfr.repair_handler_fk_aliases(b)
    assert res["fixed"], "non-vacuity: this is the defect the repair was built for"
    assert "Post.author_id" in (b / "main.py").read_text()
    assert "Post.user_id" not in (b / "main.py").read_text()


# --- the ambiguous case is declined, not guessed ---------------------------------------------------

def test_two_owner_columns_are_not_guessed_between(tmp_path):
    src = "inbox = db.query(Message).filter(Message.user_id == me.id).all()\n"
    b = _backend(tmp_path, src)
    res = hfr.repair_handler_fk_aliases(b)
    assert (b / "main.py").read_text() == src, "the source must be untouched"
    assert not any("Message" in f for f in res["fixed"])
    assert any("Message" in a and "recipient_id" in a for a in res["ambiguous"]), res["ambiguous"]


def test_what_the_old_code_would_have_done(tmp_path):
    """Non-vacuity, and it names the harm: without the guard this rewrites an INBOX query to the
    caller's SENT mail. `_owner_fk` still returns `sender_id` — the guard is what stops it being
    used, so this asserts the hazard is real rather than hypothetical."""
    from env_generator.llm_generator.multi_agent.runtime.route_projector import _owner_fk
    meta = {"cols": ["id", "sender_id", "recipient_id", "body"], "fks": {}}
    assert _owner_fk(meta) == "sender_id"


def test_the_decline_is_not_silent(tmp_path):
    """A repair that quietly does nothing is indistinguishable from a repair with nothing to do —
    #769/#770's rule."""
    s = inspect.getsource(heal_pipeline.HealPipeline.repair_handler_fk_aliases)
    assert 'res.get("ambiguous")' in s
    assert "DECLINED (ambiguous owner)" in s
    assert "loud failure" in s


# --- the return shape is uniform -------------------------------------------------------------------

# The uniform return shape. #974 added ``narrowed`` (models where an actor REFINEMENT
# resolved the ambiguity), so the literal moved — the INVARIANT these tests protect is that
# every return path carries the same keys, not that there are exactly two of them.
_RESULT_KEYS = {"fixed", "ambiguous", "narrowed"}


@pytest.mark.parametrize("missing", ["main.py", "models.py"])
def test_every_return_carries_both_keys(tmp_path, missing):
    """The early returns used to be `{"fixed": []}`, so a caller reading res["ambiguous"] would
    KeyError on exactly the paths where nothing happened. Same fixed-key-projection class as
    #771/#778."""
    b = _backend(tmp_path, "pass\n")
    (b / missing).unlink()
    res = hfr.repair_handler_fk_aliases(b)
    assert set(res) == _RESULT_KEYS, missing


def test_no_owner_column_at_all_is_left_alone(tmp_path):
    b = tmp_path / "backend"
    b.mkdir()
    (b / "models.py").write_text(
        "from sqlalchemy import Column, Integer\nfrom .base import Base\n\n"
        "class Tag(Base):\n    __tablename__ = 'tags'\n    id = Column(Integer, primary_key=True)\n",
        encoding="utf-8")
    (b / "main.py").write_text("x = Tag.user_id\n", encoding="utf-8")
    res = hfr.repair_handler_fk_aliases(b)
    assert set(res) == _RESULT_KEYS
    assert not any(res.values()), f"nothing should have been touched: {res}"
    assert (b / "main.py").read_text() == "x = Tag.user_id\n"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
