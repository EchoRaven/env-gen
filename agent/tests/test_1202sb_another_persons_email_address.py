r"""#1202sb: a hand-written route that publishes somebody else's email address.

tiktok-r126, live and unauthenticated:

    GET /api/explore  ->  {"items": [{..., "author": {..., "email":
                          "bts_official_bighit@example.com"}}]}

An unprimed judge browsing the app reported it without having been asked to look for anything
of the kind. It is two defects in one line: a product does not publish its users' addresses,
and an agent reading the API learns something no screen ever shows.

The framework already forbids exactly this. `#1202jb`'s `_PRIVATE_ACTOR_COLS_1202JB` is the
denylist of columns an actor row must not show to anyone who is not that actor, and every
PROJECTED read path applies it. `custom_routes.py` is hand-written, so it applies to nothing:
r126 selects `u."email" AS author_email` inside a join and puts it straight in the response.
One fact, many emitters -- which is why this gate READS that list instead of carrying a copy,
and why a test below fails if someone inlines one.

Narrow twice, and both narrowings earn their keep:
  * the alias must name a THIRD PARTY, never the caller -- `/auth/me` returning your own
    address is correct, and `my_email` is not a leak;
  * the statement must JOIN, because a row fetched by the caller's own id is their own row.

3 of the 170 corpus backends hit it: r123, r126, and r129 -- which delivered two milestones
with six such paths in it.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.deliverability import (
    _third_party_private_columns_1202sb as gate)


def _backend(tmp_path, code, name="custom_routes.py"):
    be = tmp_path / "backend"
    be.mkdir(parents=True, exist_ok=True)
    (be / name).write_text(code)
    return tmp_path


_R126 = '''
def explore(db):
    rows = db.execute("""
        SELECT v.id, v.caption, u."name" AS author_name, u."email" AS author_email
        FROM videos v JOIN users u ON u.id = v.author_id
    """)
    return [{"id": r.id, "author": {"name": r.author_name, "email": r.author_email}}
            for r in rows]
'''


# --- it fires -------------------------------------------------------------------------

def test_the_r126_query_is_caught(tmp_path):
    out = gate(_backend(tmp_path, _R126))
    assert out and "author_email" in out[0]


@pytest.mark.parametrize("alias", ["author_email", "host_email", "creator_email",
                                   "actor_email", "participant_email", "owner_phone"])
def test_every_third_party_prefix_is_caught(tmp_path, alias):
    col = alias.split("_", 1)[1]
    code = 'q = "SELECT u.%s AS %s FROM posts p JOIN users u ON u.id = p.user_id"' % (col, alias)
    assert gate(_backend(tmp_path, code)), alias


def test_the_count_and_the_list_agree(tmp_path):
    code = ('a = "SELECT u.email AS author_email FROM v JOIN users u ON 1=1"\n'
            'b = "SELECT u.phone AS host_phone FROM r JOIN users u ON 1=1"\n')
    out = gate(_backend(tmp_path, code))[0]
    assert out.startswith("2 hand-written read path(s)")
    assert "author_email" in out and "host_phone" in out
    assert "more not shown" not in out


# --- and what it lets through ---------------------------------------------------------

@pytest.mark.parametrize("alias", ["my_email", "own_email", "self_email", "current_email",
                                   "viewer_email"])
def test_your_own_address_is_not_a_leak(tmp_path, alias):
    """/auth/me returning the caller's own address is the correct behaviour."""
    code = 'q = "SELECT u.email AS %s FROM sessions s JOIN users u ON u.id = s.user_id"' % alias
    assert gate(_backend(tmp_path, code)) == []


def test_a_row_fetched_by_the_callers_own_id_is_not_a_leak(tmp_path):
    """No JOIN: the query returns one actor's own record."""
    code = 'q = "SELECT email AS author_email FROM users WHERE id = :uid"'
    assert gate(_backend(tmp_path, code)) == []


@pytest.mark.parametrize("name", ["models.py", "seed_data.py", "schemas.py"])
def test_declaring_the_column_is_not_publishing_it(tmp_path, name):
    """models.py declares, seed_data.py loads, schemas.py shapes. The leak is a READ PATH
    choosing to emit one."""
    code = 'q = "SELECT u.email AS author_email FROM v JOIN users u ON 1=1"'
    assert gate(_backend(tmp_path, code, name=name)) == []


def test_a_clean_backend_is_silent(tmp_path):
    code = 'q = "SELECT u.username AS author_name FROM videos v JOIN users u ON u.id = v.uid"'
    assert gate(_backend(tmp_path, code)) == []


def test_no_backend_at_all_is_silent(tmp_path):
    assert gate(tmp_path) == []


def test_an_operator_can_turn_it_off(tmp_path, monkeypatch):
    app = _backend(tmp_path, _R126)
    assert gate(app), "precondition: it fires without the switch"
    monkeypatch.setenv("ENVGEN_PRIVATE_COLUMN_GATE", "0")
    assert gate(app) == []


def test_an_unreadable_file_does_not_raise(tmp_path):
    be = tmp_path / "backend"
    be.mkdir(parents=True)
    (be / "custom_routes.py").write_bytes(b"\xff\xfe SELECT u.email AS author_email JOIN")
    assert isinstance(gate(tmp_path), list)


# --- one list, one fact ---------------------------------------------------------------

def test_the_gate_reads_the_frameworks_own_denylist():
    """If this is ever inlined, the two copies drift and a column is private in projected
    reads and public in hand-written ones -- which is the whole bug."""
    import inspect

    from env_generator.llm_generator.multi_agent.runtime import deliverability

    src = inspect.getsource(deliverability._third_party_private_columns_1202sb)
    assert "_PRIVATE_ACTOR_COLS_1202JB" in src, "the denylist was copied instead of imported"


def test_a_column_added_to_the_denylist_is_picked_up(tmp_path, monkeypatch):
    from env_generator.llm_generator.multi_agent.runtime import route_projector

    monkeypatch.setattr(route_projector, "_PRIVATE_ACTOR_COLS_1202JB", frozenset({"nickname"}))
    code = 'q = "SELECT u.nickname AS author_nickname FROM v JOIN users u ON 1=1"'
    assert gate(_backend(tmp_path, code)), "the gate is not reading the live list"


def test_the_delivery_gate_consults_it():
    import inspect

    from env_generator.llm_generator.multi_agent.runtime import deliverability

    assert ("blockers.extend(_third_party_private_columns_1202sb(app_root))"
            in inspect.getsource(deliverability))
