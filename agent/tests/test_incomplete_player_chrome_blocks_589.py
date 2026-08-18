r"""#589: the chrome checklist has to cut both ways — a shell must not PASS on similarity.

#588 demoted complete-chrome players to advisory, but it skipped every screen already above the
bar, so it never saw the worse half of the same defect. Measured over the 31 runs that produced
a player page, holistic similarity there is not noisy, it is INVERTED:

    chrome COMPLETE  n=26  mean 0.605  max 0.72   -- every one of them BLOCKED
    chrome SHELL     r107 0.92  (7 of 8 controls missing)   -- PASSED
                     r106 0.85  (5 missing)                 -- PASSED
                     r138 0.80  (2 missing)                 -- PASSED

r107's own verdict explains it: "Player chrome closely matches the reference", fixes = "group
the flag icon and Ad counter into one dark rounded chip". The reference is an AD frame, so a
page reproducing the ad chrome (Back/Report/Fullscreen, nothing else) outscores a real player.

Blocking cannot key on `missing != []` — every ordinary page is missing all of them. The
applicability test is the framework's OWN `_screen_is_player_449`, the same predicate that
decided to emit the cluster for this screen.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    _screen_is_player_449,
    player_control_labels,
)
from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
    player_chrome_missing,
)

_FULL = "\n".join(f'<button aria-label="{l}" />' for l in sorted(player_control_labels()))
# what r107 actually shipped: the AD chrome, none of the playback cluster
_AD_SHELL = ('<button aria-label="Back" /><button aria-label="Report" />'
             '<button aria-label="Fullscreen" />')


def _page(tmp_path, name, body):
    d = tmp_path / "src" / "pages"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.jsx").write_text(body, encoding="utf-8")
    return tmp_path


# --- the applicability predicate is the framework's own, and it is narrow -------------------

def test_the_verdict_screen_shape_is_enough_to_classify_a_player():
    """`_persist_verdict` only has the verdict screen (name/route), not the design screen."""
    assert _screen_is_player_449({"name": "player", "route": "/watch/:titleId"})
    assert _screen_is_player_449({"name": "player", "route": ""})


def test_ordinary_screens_are_not_players_so_the_block_cannot_reach_them():
    for s in ({"name": "login", "route": "/login"},
              {"name": "browse_home", "route": "/browse"},
              {"name": "my_list", "route": "/my-list"},
              {"name": "games", "route": "/games"},
              {"name": "title_detail", "route": "/title/:id"}):
        assert not _screen_is_player_449(s), s
        # ...even though the checklist reports every control "missing" for them
        assert s["name"] != "player"


# --- the two halves of the same checklist ---------------------------------------------------

def test_the_r107_shell_is_missing_the_whole_playback_cluster(tmp_path):
    fe = _page(tmp_path, "PlayerPage", _AD_SHELL)
    missing = player_chrome_missing(fe, "PlayerPage")
    assert "Fullscreen" not in missing          # the one real control it did ship
    assert {"Pause", "Rewind 10 seconds", "Forward 10 seconds",
            "Subtitles", "Episodes", "Next episode", "Volume"} <= set(missing), missing


def test_a_complete_player_reports_nothing_missing(tmp_path):
    assert player_chrome_missing(_page(tmp_path, "PlayerPage", _FULL), "PlayerPage") == []


# --- the gate wiring -------------------------------------------------------------------------

def _persist_src():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    return inspect.getsource(vf._persist_verdict)


def test_a_high_scorer_is_no_longer_skipped_before_the_chrome_is_read():
    """The #588 shape (`or _sim(_s) >= min_similarity: continue`) hid r107 entirely.

    ★ Asserted as SEMANTICS. This used to pin the literal
    `if _sim(_s) >= min_similarity and not _is_player:`, and #942 replaced that with a skip on the
    WORSE of the recorded and live scores — strictly more inspection, exactly what this test wants
    — which turned it red. Fourth spelling assertion this session to forbid its own improvement
    (#926, #621's locator, #900's row line, this). The rule the test actually holds: the skip must
    be guarded by `_is_player` and must not be keyed on the raw merged similarity alone.
    """
    import ast
    src = _persist_src()
    assert 'if _s.get("advisory") or _sim(_s) >= min_similarity' not in src
    assert "_is_player = bool(_screen_is_player_449(_s))" in src
    fn = ast.parse(src.strip()).body[0]
    skips = [n for n in ast.walk(fn) if isinstance(n, ast.If)
             and any(isinstance(b, ast.Continue) for b in n.body)
             and "_is_player" in ast.dump(n.test)]
    assert skips, "the chrome skip must still be gated on _is_player"
    left = skips[0].test.values[0].left if isinstance(skips[0].test, ast.BoolOp) else None
    assert isinstance(left, ast.Name) and left.id != "_sim", (
        "the skip must not be keyed on the raw merged score; #942 uses the worse of merged+live")


def test_the_block_is_gated_on_the_framework_predicate_not_on_missing_alone():
    src = _persist_src()
    i = src.index("#589: the framework emitted this cluster")
    window = src[i:i + 400]
    assert "if _is_player:" in window
    assert '_s["chrome_incomplete"] = True' in window


def test_an_incomplete_player_fails_the_gate_whatever_it_scored():
    src = _persist_src()
    assert ('all(_sim(s) >= min_similarity and not s.get("chrome_incomplete")' in src), src[-600:]


def test_the_reported_average_is_deliberately_untouched():
    """#542a's `_blocking_average` stays a pure similarity mean — the block is a separate
    reason, not a score edit, so the recorded fidelity metric remains comparable."""
    src = _persist_src()
    i = src.index("_blocking_average = ")
    assert "chrome_incomplete" not in src[i:i + 400]


def test_the_demotion_still_requires_being_below_the_bar():
    """A complete-chrome player ABOVE the bar is now inspected too — it must simply pass,
    not be relabelled advisory."""
    src = _persist_src()
    i = src.index("if _missing == []")
    window = src[i:i + 500]
    assert "if _sim(_s) < min_similarity:" in window
    assert '_s["advisory"] = True' in window


def test_the_component_field_is_preferred_over_the_name_guess():
    src = _persist_src()
    assert '_cands = [_s.get("component"),' in src


def test_an_unreadable_page_blocks_nothing(tmp_path):
    """No evidence must never manufacture a failure."""
    assert player_chrome_missing(tmp_path, "PlayerPage") is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
