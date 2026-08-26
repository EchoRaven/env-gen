"""#1115: source churn only earns a re-validation while the OUTCOME is still moving.

`maybe_refresh_stale_build_checklist` grants a refresh — zeroing
`_framework_validation_attempts` — whenever the combined backend|frontend source
signature moved. On smoke-notes the frontend lane edited JSX on nearly every tick,
so it spent all 10 refreshes; and because each one zeroed `_attempts`,
`_post_cap_1048` stayed False, so SOURCE-EDIT PROGRESS reset the stuck count for
FREE (churn 0/8 across ~60 validations). The two graces reset each other and
neither livelock bound ever bit.

The cost: 58 of 60 `docker build`s failed rc=1 in ONE second with a byte-identical
host-kernel seccomp error — thrown before any app source is COPYed into the image,
so no JSX edit could ever have changed it. ~35 of the run's 39 minutes went there.

Same principle as #1114: a signature moving is not evidence the outcome will move.
Ask the outcome.
"""
import logging

import pytest

from env_generator.llm_generator.multi_agent.runtime.framework_validation import (
    maybe_refresh_stale_build_checklist,
    _CHECKLIST_REFRESH_FLAT_CAP,
    _IDENTICAL_FAILURE_STREAK_CAP_1115,
)

BLOCKED = ["verification_checklist_not_ready"]


class _Orch:
    def __init__(self, root):
        self.output_dir = str(root)
        self._current_milestone_version = "1.0.0"
        self._framework_validation_attempts = 7
        self._logger = logging.getLogger("stub_fwval_1115")


@pytest.fixture
def orch(tmp_path):
    (tmp_path / "app" / "backend").mkdir(parents=True)
    (tmp_path / "app" / "frontend" / "src").mkdir(parents=True)
    (tmp_path / "app" / "backend" / "custom_routes.py").write_text("x = 1\n")
    (tmp_path / "app" / "frontend" / "src" / "App.jsx").write_text("export default 1\n")
    return _Orch(tmp_path)


def _churn_frontend(orch, n):
    """What the frontend lane was doing every tick: edit a page, change the sig."""
    from pathlib import Path
    p = Path(orch.output_dir) / "app" / "frontend" / "src" / "App.jsx"
    p.write_text("export default %d\n" % n)


def _spend_the_flat_budget(orch):
    for i in range(_CHECKLIST_REFRESH_FLAT_CAP):
        _churn_frontend(orch, i)
        assert maybe_refresh_stale_build_checklist(orch, BLOCKED) is True


def test_churn_stops_earning_refreshes_once_the_failure_stops_changing(orch):
    _spend_the_flat_budget(orch)

    # the build now fails byte-identically, over and over
    orch._fwval_identical_failure_streak = _IDENTICAL_FAILURE_STREAK_CAP_1115

    for i in range(5):
        _churn_frontend(orch, 100 + i)   # the lane keeps editing; the sig keeps moving
        assert maybe_refresh_stale_build_checklist(orch, BLOCKED) is False, (
            "source churn bought another docker build against a failure that had "
            "already reproduced byte-for-byte %d times"
            % _IDENTICAL_FAILURE_STREAK_CAP_1115
        )


def test_a_moving_outcome_still_earns_refreshes(orch):
    """The mechanism must survive: #1115 removes dead retries, not the grace."""
    _spend_the_flat_budget(orch)

    for i in range(4):
        _churn_frontend(orch, 200 + i)
        orch._fwval_identical_failure_streak = 0   # each build failed differently
        assert maybe_refresh_stale_build_checklist(orch, BLOCKED) is True, (
            "a genuinely converging build stopped being re-validated"
        )


def test_a_changed_failure_detail_restores_the_grace(orch):
    """A partial fix changes the error; the streak resets and churn counts again."""
    _spend_the_flat_budget(orch)

    orch._fwval_identical_failure_streak = _IDENTICAL_FAILURE_STREAK_CAP_1115
    _churn_frontend(orch, 300)
    assert maybe_refresh_stale_build_checklist(orch, BLOCKED) is False

    orch._fwval_identical_failure_streak = 0       # the build got further
    _churn_frontend(orch, 301)
    assert maybe_refresh_stale_build_checklist(orch, BLOCKED) is True


def test_the_flat_budget_is_untouched_by_a_dead_failure(tmp_path):
    """#120's original guarantee: three refreshes regardless of any signature.

    A stale checklist with NO source movement at all still self-heals — that path
    predates the settle branch and #1115 must not narrow it.
    """
    (tmp_path / "app" / "backend").mkdir(parents=True)
    (tmp_path / "app" / "backend" / "custom_routes.py").write_text("x = 1\n")
    o = _Orch(tmp_path)
    o._fwval_identical_failure_streak = 99        # as dead as it gets

    granted = sum(1 for _ in range(_CHECKLIST_REFRESH_FLAT_CAP)
                  if maybe_refresh_stale_build_checklist(o, BLOCKED))
    assert granted == _CHECKLIST_REFRESH_FLAT_CAP


def test_not_armed_when_the_checklist_is_not_the_blocker(orch):
    assert maybe_refresh_stale_build_checklist(orch, ["business_chain_failing"]) is False
    assert maybe_refresh_stale_build_checklist(orch, []) is False


def test_the_streak_counts_only_byte_identical_failures(orch):
    """The recording half: a changed detail must reset, an identical one must count."""
    from env_generator.llm_generator.multi_agent.runtime.framework_validation import (
        _note_failure_detail_1115,
    )

    seccomp = ["docker_up:docker build FAILED (attempt 1/1). Transcript tail:"]

    assert _note_failure_detail_1115(orch, seccomp) == 0      # first sight
    assert _note_failure_detail_1115(orch, seccomp) == 1
    assert _note_failure_detail_1115(orch, seccomp) == 2
    assert _note_failure_detail_1115(orch, seccomp) == 3      # now dead by the cap

    # same failing CHECK, different cause — the build moved, so the streak restarts
    assert _note_failure_detail_1115(
        orch, ["docker_up:npm ERR! missing script: build"]) == 0

    # and a set that grows/shrinks is a change too
    assert _note_failure_detail_1115(
        orch, ["docker_up:npm ERR! missing script: build", "api_smoke:404"]) == 0


def test_the_streak_never_raises_on_a_hostile_orch():
    class _Hostile:
        @property
        def _fwval_failure_detail_sig(self):
            raise RuntimeError("boom")

    from env_generator.llm_generator.multi_agent.runtime.framework_validation import (
        _note_failure_detail_1115,
    )

    assert _note_failure_detail_1115(_Hostile(), ["x"]) == 0
