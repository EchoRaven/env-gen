"""FIX #175 — a frontend that renders a member field with a FABRICATED literal fallback
(`place.rating || '4.5'`, `? place.name : 'HI Point Montara Lighthouse'`) ships fake data
whenever the real field is absent — and gmrun9 proved the field is OFTEN absent because the
name drifted (`place.reviews` vs the model's `review_count`, `place.price` vs `price_level`)
so the fallback fires on EVERY row. #170 added a PROMPT rule against this; the lane ignored
it (the delivered SearchResultsPage is full of them), so make it an ENFORCING delivery gate.

The classifier flags a member-access fallback to a literal that looks like REAL DOMAIN DATA
(a rating/price/count with a digit, a multi-word name/address/sentence, a capitalized proper
noun) — but NOT honest absence conventions ('N/A', 'Untitled', 'Anonymous', 'Loading…'),
error messages ('API request failed'), falsy structural defaults (`|| []`, `|| ''`, `|| 0`),
or lowercase enum states (`|| 'active'`). LOCAL-ONLY.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LLM = ROOT / "env_generator" / "llm_generator"
for _p in (ROOT, LLM):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from multi_agent.runtime.frontend_audit import invented_field_fallback_blockers  # noqa: E402


def _fe(tmp_path, files):
    src = tmp_path / "frontend" / "src"
    src.mkdir(parents=True, exist_ok=True)
    for rel, txt in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt)
    return src


def _blk(tmp_path, jsx):
    return invented_field_fallback_blockers(_fe(tmp_path, {"P.jsx": jsx}))


# ── FLAG: fabricated domain data ──
def test_flags_numeric_string_fallback(tmp_path):
    assert _blk(tmp_path, "<span>{place.rating || '4.5'}</span>")


def test_flags_count_fallback(tmp_path):
    assert _blk(tmp_path, "<span>({place.reviews || '1,234'})</span>")


def test_flags_multiword_address_fallback(tmp_path):
    assert _blk(tmp_path, "<div>{place.address || 'San Francisco, CA'}</div>")


def test_flags_sentence_fallback(tmp_path):
    assert _blk(tmp_path, "<p>{review.text || 'Great food and service!'}</p>")


def test_flags_capitalized_proper_noun_fallback(tmp_path):
    assert _blk(tmp_path, "<span>{place.category || 'Hotel'}</span>")


def test_flags_ternary_placeholder_branch(tmp_path):
    assert _blk(tmp_path, "<h1>{selected ? selectedPlace.name : 'HI Point Montara Lighthouse'}</h1>")


def test_reports_file_and_line(tmp_path):
    b = _blk(tmp_path, "a\n<span>{place.rating || '4.5'}</span>\n")
    assert any("P.jsx" in x and ":2" in x for x in b), b


# ── DON'T FLAG: honest ──
def test_ignores_error_message_fallback(tmp_path):
    assert _blk(tmp_path, "throw new Error(error.message || 'API request failed')") == []


def test_ignores_honest_absence_conventions(tmp_path):
    jsx = ("<div>{user.name || 'Anonymous'}{doc.title || 'Untitled'}"
           "{x.y || 'N/A'}{s.v || 'Unknown'}{g.h || 'Loading...'}</div>")
    assert _blk(tmp_path, jsx) == []


def test_ignores_falsy_structural_defaults(tmp_path):
    jsx = "const a = items || []; const b = obj.x || ''; const c = p.n || 0; const d = q.r || {};"
    assert _blk(tmp_path, jsx) == []


def test_ignores_lowercase_enum_state(tmp_path):
    assert _blk(tmp_path, "<span>{item.status || 'active'}</span>") == []


def test_ignores_zero_count_default(tmp_path):
    # gmrun11 ABORTED on this: `place.review_count || '0'` — '0' is the honest "zero reviews"
    # state, NOT fabricated data. The lane can't "fix" a legit zero default → non-convergence.
    assert _blk(tmp_path, "<span>{place.review_count || '0'}</span>") == []


def test_ignores_zero_variants(tmp_path):
    jsx = ("<div>{a.n || '0'}{b.n || '0.0'}{c.p || '$0'}{d.pct || '0%'}"
           "{e.c || '0 reviews'}{f.r || '0 results'}</div>")
    assert _blk(tmp_path, jsx) == []


def test_still_flags_nonzero_numeric(tmp_path):
    # the real fabrications must STILL be caught (only ZERO is honest)
    assert _blk(tmp_path, "<span>{place.rating || '4.5'}</span>")
    assert _blk(tmp_path, "<span>{place.reviews || '1,234'}</span>")
    assert _blk(tmp_path, "<span>{place.time || '5 min'}</span>")


def test_ignores_capitalized_state_enum(tmp_path):
    # a capitalized STATE default is honest (not fabricated specific DATA)
    jsx = "<div>{a.status || 'Active'}{b.state || 'Pending'}{c.vis || 'Public'}</div>"
    assert _blk(tmp_path, jsx) == []


def test_still_flags_capitalized_proper_noun(tmp_path):
    # ...but a fabricated category/name proper noun is STILL caught
    assert _blk(tmp_path, "<span>{place.category || 'Hotel'}</span>")


# ── archive-audit FALSE-POSITIVES the lane can NEVER clear (they're honest absence states);
#    flagging them aborts runs (gmrun11). Each MUST be excluded. ──
def test_ignores_x_not_available(tmp_path):
    jsx = ("<div>{p.hours || 'Hours not available'}{p.phone || 'Phone not available'}"
           "{p.website || 'Website not available'}</div>")
    assert _blk(tmp_path, jsx) == []


def test_ignores_no_prefix_absence(tmp_path):
    jsx = ("<div>{l.description || 'No description'}{i.note || 'No note added.'}"
           "{p.desc || 'No additional information available.'}</div>")
    assert _blk(tmp_path, jsx) == []


def test_ignores_unknown_prefix(tmp_path):
    jsx = ("<div>{i.place_name || 'Unknown Place'}{d.line || 'Unknown Line'}"
           "{d.destination || 'Unknown Destination'}{r.distance || 'Unknown distance'}</div>")
    assert _blk(tmp_path, jsx) == []


def test_ignores_anonymous_user(tmp_path):
    assert _blk(tmp_path, "<span>{user.name || 'Anonymous User'}</span>") == []


def test_ignores_hex_color_default(tmp_path):
    jsx = "<div style={{color: line.color || '#3b82f6'}}>{dep.color || '#FFF'}</div>"
    assert _blk(tmp_path, jsx) == []


def test_ignores_asset_path_default(tmp_path):
    jsx = ("<img src={place.photo_url || '/assets/placeholders/ph-img-1.svg'}/>"
           "<img src={u.avatar || '/assets/icons/photo-camera_24.svg'}/>")
    assert _blk(tmp_path, jsx) == []


def test_ignores_unicode_escape_dash(tmp_path):
    # gmrun12: the lane fixed fabrications with the honest em-dash written as a JS unicode
    # escape `'—'` (renders '—'). The static source has digits (2014) but it's honest —
    # decode the escape before classifying, else M2 aborts on the lane's correct fix.
    assert _blk(tmp_path, "<h1>{place.name || '\\u2014'}</h1>") == []
    assert _blk(tmp_path, "<span>{p.desc || '\\u2026'}</span>") == []   # ellipsis …


def test_still_flags_real_fabrications_after_hardening(tmp_path):
    # the genuine invented data across archives must all REMAIN flagged
    for jsx in ("{place.phone || '(555) 123-4567'}",
                "{place.address || 'San Francisco, CA'}",
                "{review.author || 'Pho Ha Noi'}",
                "{review.text || 'Great food and service!'}",
                "{place.capacity || 'Sleeps 4'}",
                "{place.rating || '4.5'}"):
        assert _blk(tmp_path, "<span>" + jsx + "</span>"), jsx


def test_ignores_variable_fallback(tmp_path):
    # `X.y || someVar` is not a hardcoded literal
    assert _blk(tmp_path, "<span>{place.name || defaultName}</span>") == []


def test_clean_page_no_blockers(tmp_path):
    assert _blk(tmp_path, "<span>{place.name}</span><span>{place.rating}</span>") == []


def test_env_gate_disables(tmp_path, monkeypatch):
    monkeypatch.setenv("ENVGEN_INVENTED_FIELD_GATE", "0")
    assert _blk(tmp_path, "<span>{place.rating || '4.5'}</span>") == []


def test_blocker_canonicalizes_to_delivery_token():
    from multi_agent.runtime.delivery_gate import _deliverability_check_token
    blocker = ("frontend renders a FABRICATED fallback `place.rating || '4.5'` "
               "(SearchResultsPage.jsx:130) — it shows invented data …")
    assert _deliverability_check_token(blocker) == "deliverability_fabricated_field_fallback"


def test_remediation_owner_maps_token_to_frontend():
    # gmrun10 (live) caught this: the gate-minted token MUST live in the gate-level
    # _GATE_OWNER map, not _CHECK_OWNER (dead code for gate tokens) — else the delivery
    # decline logs 'NO remediation owner' and rides to STUCK with the lane idle.
    import ast
    from pathlib import Path
    from multi_agent.runtime import remediation_dispatcher as rd
    tree = ast.parse(Path(rd.__file__).read_text(encoding="utf-8"))
    owners = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict) and any(
                isinstance(t, ast.Name) and t.id == "_GATE_OWNER" for t in node.targets):
            for k, v in zip(node.value.keys, node.value.values):
                if (isinstance(k, ast.Constant) and isinstance(v, ast.Tuple) and v.elts
                        and isinstance(v.elts[0], ast.Constant)):
                    owners[k.value] = v.elts[0].value
    assert owners.get("deliverability_fabricated_field_fallback") == "frontend"
