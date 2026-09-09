"""#1202jc: `art` matched inside `cart_token`, and #1202ip turned that into a live path.

The keep-list that decides which of a FOLDED table's columns ride along used
`any(k in col.lower() for k in _IMAGEISH_1202FH)`, and `"art"` is one of the keys. It matches
inside `cart_token`, `partner_email`, `participant_name`, `started_at` and `departure_time`.

That was harmless while the keep-list only chose columns for a page to draw. #1202ip made it
reachable: the fold now carries another table's chosen columns into a PUBLIC list read, and
#1202jb's denylist filters the READ's own columns, not the folded target's. Verified by
projecting a real model — a public `/api/orders` folding `carts` shipped `cart_token` and
`partner_email`. My own fix widened the blast radius of a rule that predated it.

A whole-token test is wrong the other way: `thumbnail`.split("_") == ["thumbnail"] does not
contain `"thumb"`, so it drops the most common image column in the corpus. Token PREFIX
satisfies both.
"""
import sys
import pathlib

_AGENT = pathlib.Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from env_generator.llm_generator.multi_agent.runtime import route_projector as RP  # noqa: E402


_MODELS_PY = '''
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Cart(Base):
    __tablename__ = "carts"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    thumbnail = Column(String)
    cart_token = Column(String)
    partner_email = Column(String)
    started_at = Column(String)


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    cart_id = Column(Integer)
    total = Column(Integer)
'''


def _models(tmp_path):
    (tmp_path / "models.py").write_text(_MODELS_PY)
    return RP._orm_models(tmp_path)


def test_the_leak_the_fold_opened_is_closed(tmp_path):
    """The end-to-end case, through the production entry point: before #1202jc this handler
    carried both columns to any anonymous caller."""
    h = RP._generate_handler("GET", "/api/orders", False, _models(tmp_path), 0, None,
                             False, set())
    src = h if isinstance(h, str) else h[0]
    assert "_m_cart" in src, "premise: the fold must actually fire here"
    assert "cart_token" not in src, src
    assert "partner_email" not in src, src


def test_the_image_column_survives(tmp_path):
    """A whole-token rule would drop `thumbnail` — 42 of them in the corpus, the most common
    image column there is. This is why the rule is prefix and not equality."""
    exp = RP._expandable_fks_1202fh(_models(tmp_path)["orders"]["cols"],
                                    _models(tmp_path), "orders")
    assert exp, exp
    cols = exp[0][2]
    assert "thumbnail" in cols, cols
    assert "name" in cols, cols
    assert "cart_token" not in cols and "partner_email" not in cols, cols


def test_it_matches_by_word_not_by_spelling():
    """The vocabulary is unchanged; only how a column is tested against it."""
    for image in ("thumbnail", "thumbnail_url", "avatar", "avatar_url", "poster",
                  "backdrop", "cover_art", "peer_avatar", "profile_photo_url",
                  "banner_image", "logo"):
        assert RP._imageish_1202jc(image), image
    for not_image in ("cart_token", "partner_email", "participant_name", "participant_id",
                      "started_at", "departure_time", "smart_reply", "chart_id"):
        assert not RP._imageish_1202jc(not_image), not_image


def test_the_old_substring_rule_would_have_failed_this():
    """Pins the difference rather than the new rule alone, so a revert cannot read as a
    refactor: every one of these is True under `any(k in col)` and False under the fix."""
    for col in ("cart_token", "partner_email", "started_at", "departure_time"):
        assert any(k in col for k in RP._IMAGEISH_1202FH), col      # old rule: matched
        assert not RP._imageish_1202jc(col), col                    # new rule: does not


def test_empty_and_none_are_not_images():
    assert not RP._imageish_1202jc("")
    assert not RP._imageish_1202jc(None)
