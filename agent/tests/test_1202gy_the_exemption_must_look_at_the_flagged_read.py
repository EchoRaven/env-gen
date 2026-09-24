"""#1202gy — the lane declares the flagged read public and the exemption looks elsewhere.

`unscoped_owner_read_findings` resolves which TABLE a handler serves by reading the code, so
it correctly flags `GET /api/explore` for returning every row of `videos`. `#1202gd`'s
exemption then looks for the contract's word on that table by NAME:

    if not (path.endswith("/" + table) or path.endswith("/" + table.replace("_", "-"))):
        continue

`/api/explore` does not end in `/videos`, so the endpoint the finding is actually about is
skipped, and only `/api/videos` is consulted.

r101, live: #1202gt told the lane "publicness is decided in the CONTRACT
(`auth_required=false`)". The lane did exactly that — `/api/explore` schema.auth_required went
to False, and the projected read became `db.query(Video).limit(100).all()`. The exemption
still returned False, because `/api/videos` remained authed, and the blocker stayed up. The
lane followed the instruction and was blocked anyway.

Sixth instance today of one datum with two readers keyed on different things (after #1202ga,
#1202fu, #1202fq, #1202gr and #1202gx). The finding knows which endpoint it is about; the
exemption should be asked about THAT endpoint, not a sibling that shares the table's name.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.backend_audit import _declared_public_1202gd  # noqa: E402

_SPEC = {"entities": [{"name": "videos", "fields": ["id"], "visibility": "public"},
                      {"name": "my_list", "fields": ["id"], "visibility": "owner"}]}


def _project(tmp_path, endpoints, owner_scoped=()):
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True)
    (tmp_path / "design").mkdir()
    (tmp_path / "design" / "reference_spec.json").write_text(json.dumps(_SPEC),
                                                            encoding="utf-8")
    hubs = tmp_path / "shared" / "hubs"
    hubs.mkdir(parents=True)
    (hubs / "registryhub_endpoints.json").write_text(json.dumps(endpoints), encoding="utf-8")
    # #1202hm: the corroborating signal moved to the TABLE. Written explicitly so these cases
    # cannot pass merely because the ledger is absent (which reads as "stay strict").
    (hubs / "registryhub_tables.json").write_text(json.dumps(
        {t: {"name": t, "metadata": ({} if t not in (owner_scoped or ()) else
                                     {"owner_scoped_reads": True})}
         for t in ("videos", "my_list")}), encoding="utf-8")
    return be


# r101's shape: the FEED route is declared public, the name-matched collection is not.
_R101 = {
    "GET /api/videos": {"method": "GET", "path": "/api/videos",
                        "schema": {"auth_required": True}, "metadata": {}},
    "GET /api/explore": {"method": "GET", "path": "/api/explore",
                         "schema": {"auth_required": False}, "metadata": {}},
}


def test_no_sibling_endpoint_can_hold_the_exemption_down(tmp_path):
    """r101's failure, stated as the property that now prevents it. #1202hm corroborates the
    materials with the TABLE's `owner_scoped_reads`, so which sibling read happens to be
    authenticated cannot decide whether published rows are published. Both paths agree, and
    they agree even when BOTH endpoints require a login -- the shape that blocked r105."""
    be = _project(tmp_path, _R101)
    assert _declared_public_1202gd(be, "videos", "/api/explore") is True
    assert _declared_public_1202gd(be, "videos", "/api/videos") is True
    authed_everywhere = {k: {**v, "schema": {"auth_required": True}}
                         for k, v in _R101.items()}
    be2 = _project(tmp_path / "b", authed_everywhere)
    assert _declared_public_1202gd(be2, "videos", "/api/videos") is True


def test_the_verdict_no_longer_depends_on_the_path(tmp_path):
    """`path` is retained in the signature for the caller but is not read. A table-level flag
    has no path ambiguity, which is what removes r101's whole class of near-miss."""
    be = _project(tmp_path, _R101)
    for arg in ("/api/explore", "/api/videos", "/api/nowhere", ""):
        assert _declared_public_1202gd(be, "videos", arg) is True, arg
    assert _declared_public_1202gd(be, "videos") is True


def test_the_materials_half_is_still_required(tmp_path):
    """#647 — a contract alone released a real `my_list` in the corpus. Both signals stand."""
    eps = {"GET /api/my-list": {"method": "GET", "path": "/api/my-list",
                                "schema": {"auth_required": False}, "metadata": {}}}
    be = _project(tmp_path, eps)
    assert _declared_public_1202gd(be, "my_list", "/api/my-list") is False


def test_a_table_the_contract_scopes_is_never_exempted(tmp_path):
    """Was `test_an_authed_flagged_read_is_not_exempted`, which read the LOGIN flag. The
    contract's own read-scoping flag is what refuses now, and it refuses on every path."""
    be = _project(tmp_path, _R101, owner_scoped=("videos",))
    assert _declared_public_1202gd(be, "videos", "/api/explore") is False
    assert _declared_public_1202gd(be, "videos") is False


def test_the_audit_still_asks_per_finding(tmp_path):
    """The audit must consult the exemption for the table the FINDING is about. #1202hm made
    the verdict path-independent, so this no longer pins the argument spelling (#782) — it
    asserts the outcome: a finding on a declared-public, non-owner-scoped table is dropped."""
    from multi_agent.runtime.backend_audit import unscoped_owner_read_findings
    be = _project(tmp_path, _R101)
    (be / "models.py").write_text(
        "from sqlalchemy import Column, Integer, ForeignKey\n"
        "from database import Base\n\n"
        "class Video(Base):\n"
        "    __tablename__ = 'videos'\n"
        "    id = Column(Integer, primary_key=True)\n"
        "    author_id = Column(Integer, ForeignKey('users.id'))\n", encoding="utf-8")
    (be / "main.py").write_text(
        "@app.get('/api/explore')\n"
        "def _projected_get_api_explore_0(db=Depends(get_db), user=Depends(get_current_user)):\n"
        "    rows = db.query(Video).limit(100).all()\n"
        "    return {'items': rows}\n", encoding="utf-8")
    assert unscoped_owner_read_findings(be) == []
