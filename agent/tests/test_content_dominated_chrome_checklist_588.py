r"""#588: on a content-dominated screen, holistic similarity scores the CONTENT, not the build.

The player is a full-bleed video surface. r142's reference happened to capture an AD state
("Ad 12", "All American begins after ads"), so the judge charged the implementation for missing
an ad system nothing asked it to build — `copy` 0.50 was literally 'Ad 12' vs 'Disclosure Day',
and even layout/components were compared against an ad chrome carrying FEWER controls than the
implementation shipped.

What the generator actually controls there is the CHROME, and the framework already defines it:
`_player_controls_jsx_449` emits a named control cluster. Measured on the real trees — and this
is the point — holistic similarity could NOT tell these two apart:

    r139  PlayerPage   87 lines, ALL 8 controls present   scored 0.55
    r142  PlayerPage  118 lines, only `Back`              scored 0.50

The checklist can. r139's chrome is complete, so its score is measuring content → advisory.
r142's player is genuinely a shell → keeps blocking, with the missing controls listed.
"""
import pytest

from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
    player_control_labels,
)
from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
    player_chrome_missing,
)

_FULL = "\n".join(f'<button aria-label="{l}" />' for l in sorted(player_control_labels()))


def _page(tmp_path, name, body):
    d = tmp_path / "src" / "pages"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.jsx").write_text(body, encoding="utf-8")
    return tmp_path


def test_the_vocabulary_comes_from_the_emitter_itself():
    v = player_control_labels()
    assert {"Pause", "Volume", "Fullscreen", "Subtitles"} <= set(v), v
    assert len(v) >= 6


def test_a_complete_chrome_reports_nothing_missing(tmp_path):
    fe = _page(tmp_path, "PlayerPage", _FULL)
    assert player_chrome_missing(fe, "PlayerPage") == []


def test_the_r142_shell_reports_every_control(tmp_path):
    fe = _page(tmp_path, "PlayerPage", '<button aria-label="Back" />')
    missing = player_chrome_missing(fe, "PlayerPage")
    assert missing == sorted(player_control_labels()), missing


def test_one_missing_control_still_blocks_and_is_named(tmp_path):
    body = _FULL.replace('<button aria-label="Fullscreen" />', "")
    fe = _page(tmp_path, "PlayerPage", body)
    assert player_chrome_missing(fe, "PlayerPage") == ["Fullscreen"]


def test_a_non_player_page_can_never_qualify(tmp_path):
    """Self-gating: the demotion needs ALL controls, so an ordinary page never gets it."""
    fe = _page(tmp_path, "LoginPage", '<form><input aria-label="Email address" /></form>')
    assert player_chrome_missing(fe, "LoginPage") == sorted(player_control_labels())


def test_a_missing_page_is_not_an_answer(tmp_path):
    """`None` means "question does not apply" — the caller must leave the screen alone."""
    assert player_chrome_missing(tmp_path, "NoSuchPage") is None
    assert player_chrome_missing(tmp_path, "") is None


def test_the_demotion_is_gated_on_being_below_the_bar_and_not_already_advisory():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    src = inspect.getsource(vf._persist_verdict)
    i = src.index("#588")
    window = src[i:i + 2400]
    # #589 split the old single guard: already-advisory screens are still skipped outright,
    # and the demotion itself still requires being below the bar.
    assert 'if _s.get("advisory"):' in window, window[:300]
    assert 'if _sim(_s) < min_similarity:' in window
    assert 'if _missing == []' in window
    assert '_s["chrome_missing"] = _missing' in window   # actionable when incomplete


def test_the_demotion_records_its_reason():
    import inspect
    from env_generator.llm_generator.multi_agent.runtime import visual_fidelity as vf
    src = inspect.getsource(vf._persist_verdict)
    assert "advisory_reason" in src and "content-dominated" in src


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
