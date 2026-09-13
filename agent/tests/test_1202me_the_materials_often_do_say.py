"""#1202me — "the materials are silent in exactly these cases" was measured, and is false.

GROUND TRUTH (tiktok-web-r122, live). Its delivery gate reported:

    ⚠ CONTRACT/CHAIN CONTRADICTION (#1202kr): comments_page:GET /api/comments,
      follows_page:GET /api/follows, live_streams_page:GET /api/live_streams,
      login_page:GET /api/videos (+4 more) — ... Exactly one of the two is wrong and the
      framework cannot tell which

Its `design/reference_spec.json` entities say:

    videos public · comments public · live_streams public · sounds — · follows —

and its TABLES HUB says `visibility=None` for all five, because
`_apply_spec_visibility_1202hh` is a render-time backfill that makes no hub write. So a
ledger reading None is NOT the materials being silent — and the check was reading the ledger.

Materials outrank the contract, so for `comments`, `live_streams` and `videos` the chain is
the wrong half and the repair is unambiguous. For `follows` and `sounds` the original sentence
is correct and is kept verbatim.
"""
import inspect

import pytest

from env_generator.llm_generator.multi_agent.runtime import delivery_gate as dg

_SRC = inspect.getsource(dg._contract_denial_contradictions_1202kr)


def test_the_falsified_claim_is_gone_from_the_docstring():
    doc = " ".join((inspect.getdoc(dg._contract_denial_contradictions_1202kr) or "").split())
    # The phrase survives, but only inside the sentence that RETRACTS it. Assert the
    # retraction rather than the absence — the claim's history is worth keeping, its
    # standing as current fact is not.
    if "silent in exactly these cases" in doc:
        i = doc.index("silent in exactly these cases")
        assert "used to continue" in doc[max(0, i - 200):i], doc[max(0, i - 200):i + 60]
    assert "falsified it" in doc
    assert "render-time backfill that makes no hub write" in doc


def test_it_asks_the_materials_not_the_ledger():
    assert "_spec_visibility_1202hh" in _SRC
    assert "base_dir" in _SRC


def test_the_reader_is_reused_not_reimplemented():
    """#665/#1136: `_contract_materials_disagreement_1202ky` uses the same reader in this
    very module."""
    # CODE only — `ast.unparse` drops comments, and the docstring node is dropped explicitly.
    # Both of those NAME the file precisely because the function must not open it, and a
    # blanket `read_text(` ban is wrong too: this function legitimately reads main.py to parse
    # `_FW_PUBLIC_API_1202KH`. The property is "does not read the MATERIALS itself".
    import ast
    fn = ast.parse(_SRC.lstrip()).body[0]
    body = fn.body[1:] if (fn.body and isinstance(fn.body[0], ast.Expr)
                           and isinstance(getattr(fn.body[0], "value", None), ast.Constant)
                           and isinstance(fn.body[0].value.value, str)) else fn.body
    code = "\n".join(ast.unparse(n) for n in body)
    assert "reference_spec" not in code, (
        "this function reads the materials itself — a second reader is the drift #1136 was")
    assert "_spec_visibility_1202hh" in code, "it must go through the shared reader"


def test_a_settled_case_names_the_chain_as_the_wrong_half():
    assert "the CHAIN is the wrong half" in _SRC
    assert "widen the step to accept" in _SRC
    assert "Do NOT register the endpoint auth_required=true" in _SRC
    assert "#1202me" in _SRC


def test_a_silent_case_keeps_the_original_sentence():
    """★ Non-regression: where the materials really are silent, the old advice is right."""
    assert "materials are SILENT on these" in _SRC
    assert "the framework cannot tell which" in _SRC
    assert "do NOT just widen the expectation" in _SRC


def test_the_two_halves_are_split_not_merged():
    assert "_settled_1202me" in _SRC and "_open_1202me" in _SRC
    i_s = _SRC.index("if _settled_1202me:")
    i_o = _SRC.index("if _open_1202me:")
    assert i_s < i_o, "the settled half should lead — it is the actionable one"


def test_both_lists_declare_their_own_cut():
    """#1034: a count beside a silently truncated list reads as 'these are the N'."""
    i = _SRC.index("if _settled_1202me:")
    tail = _SRC[i:]
    assert tail.count("join_capped(") == 2


def test_a_missing_root_degrades_to_the_old_behaviour():
    """No base_dir ⇒ no materials ⇒ everything is 'open', which is exactly pre-#1202me."""
    i = _SRC.index("_public_me = set()")
    assert "except Exception:" in _SRC[:i]
    assert 'if _root_me else {}' in _SRC


def test_the_resource_token_skips_params_and_the_api_prefix():
    i = _SRC.index("_tok_me = next(")
    seg = _SRC[i:i + 300]
    assert 'startswith("{")' in seg
    assert '!= "api"' in seg


# ------------------------------------------------------------------ behaviour
#
# ★ Every assertion above is a source-structure claim, and ALL NINE stayed green when the
# settled/open split was mutated to "never settled". A green test can prove nothing: these
# call the function.


class _Hubs:
    def __init__(self, root):
        self.base_dir = str(root)


def _env(tmp_path, entities):
    """A run tree shaped the way this function reads it: materials + the framework's own
    public-API list inside the projected main.py."""
    import json
    (tmp_path / "design").mkdir(parents=True, exist_ok=True)
    (tmp_path / "design" / "reference_spec.json").write_text(
        json.dumps({"entities": entities}), encoding="utf-8")
    be = tmp_path / "app" / "backend"
    be.mkdir(parents=True, exist_ok=True)
    (be / "main.py").write_text(
        "_FW_PUBLIC_API_1202KH = [('GET', '/api/comments'), ('GET', '/api/follows')]\n",
        encoding="utf-8")
    return _Hubs(tmp_path)


def _chain(name, path):
    return {"name": name, "status": "failing",
            "steps": [{"method": "GET", "path": path, "expect": [403]}]}


def test_a_public_material_settles_the_contradiction(tmp_path):
    """★ r122's `comments_page` — the materials call `comments` public."""
    hubs = _env(tmp_path, [{"name": "comments", "visibility": "public"}])
    out = dg._contract_denial_contradictions_1202kr(
        None, [_chain("comments_page", "/api/comments")], hubs=hubs)
    assert "comments_page" in out
    assert "the CHAIN is the wrong half" in out
    assert "materials are SILENT" not in out


def test_a_silent_material_stays_unresolved(tmp_path):
    """★ r122's `follows_page` — the materials say nothing about `follows`."""
    hubs = _env(tmp_path, [{"name": "comments", "visibility": "public"}])
    out = dg._contract_denial_contradictions_1202kr(
        None, [_chain("follows_page", "/api/follows")], hubs=hubs)
    assert "follows_page" in out
    assert "materials are SILENT" in out
    assert "the CHAIN is the wrong half" not in out


def test_both_kinds_in_one_message_are_kept_apart(tmp_path):
    """★ r122 had both at once; merging them would give the wrong advice to half of them."""
    hubs = _env(tmp_path, [{"name": "comments", "visibility": "public"}])
    out = dg._contract_denial_contradictions_1202kr(
        None, [_chain("comments_page", "/api/comments"),
               _chain("follows_page", "/api/follows")], hubs=hubs)
    i_settled = out.index("the CHAIN is the wrong half")
    i_open = out.index("materials are SILENT")
    assert out.index("comments_page") < i_settled < out.index("follows_page") < i_open


def test_no_materials_at_all_degrades_to_the_old_message(tmp_path):
    hubs = _env(tmp_path, [])
    out = dg._contract_denial_contradictions_1202kr(
        None, [_chain("comments_page", "/api/comments")], hubs=hubs)
    assert "materials are SILENT" in out
    assert "the CHAIN is the wrong half" not in out
