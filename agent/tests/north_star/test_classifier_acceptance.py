"""Pilot classifier acceptance tests — the R1 gate target.

Reproduces docs/pilot_classifier_spec.md §7 fixture table verbatim. Each V-case
constructs a FailureContext and asserts the Verdict matches the spec's expected
verdict + signature. The ★ rows (launder-trap cases) are the load-bearing ones —
they prove §3 guards reject app-faults that the loose first draft would have
excluded.

Run: cd agent && /home/haibotong/miniconda3/envs/dt/bin/python -m pytest \
       tests/north_star/test_classifier_acceptance.py -v

Gate criteria (R1):
  (a) every V-fixture's verdict reproduces;
  (b) the adversarial pass cannot construct an app-fault that a §3 signature
      excludes as env (over-exclusion = inflation = the dangerous direction) —
      the ★ rows are the minimum bar;
  (c) the default-functional path holds for an unmatched failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make sibling classifier.py importable.
_THIS = Path(__file__).resolve()
_NORTH_STAR_DIR = _THIS.parent
if str(_NORTH_STAR_DIR) not in sys.path:
    sys.path.insert(0, str(_NORTH_STAR_DIR))

from classifier import FailureContext, Verdict, classify  # noqa: E402


# ---------------------------------------------------------------------------
# V1 / V2 — env.buildkit_recurrence: pip rich frame is the anchor
# ---------------------------------------------------------------------------


def test_V1_pip_rich_thread_with_rich_frame_is_env():
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr=(
            "#9 2.892   File \"/usr/local/lib/python3.11/site-packages/pip/_vendor/rich/live.py\", line 116, in start\n"
            "#9 2.892     self._refresh_thread.start()\n"
            "#9 2.892   File \"/usr/local/lib/python3.11/threading.py\", line 964, in start\n"
            "#9 2.892     _start_new_thread(self._bootstrap, ())\n"
            "#9 2.892 RuntimeError: can't start new thread\n"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "env"
    assert v.matched_signature == "env.buildkit_recurrence"


def test_V2_star_generated_thread_error_no_rich_frame_is_functional():
    """★ launder trap: an app-fault thread crash without a rich-frame anchor
    must NOT be classified as env."""
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr=(
            "#21 12.34   File \"/app/build_index.py\", line 88, in main\n"
            "#21 12.34     threading.Thread(target=worker).start()\n"
            "#21 12.34 RuntimeError: can't start new thread\n"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "functional"
    assert v.matched_signature is None


# ---------------------------------------------------------------------------
# V4 — jira-web vite cli.js: the canonical functional build failure
# ---------------------------------------------------------------------------


def test_V4_star_jira_web_vite_cli_is_functional():
    """★ launder trap: a build that exits non-zero because the GENERATED APP is
    broken (vite cli.js missing) must NOT be classified as env."""
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr=(
            "#33 0.560 Error [ERR_MODULE_NOT_FOUND]: Cannot find module "
            "'/app/node_modules/dist/node/cli.js' imported from /app/node_modules/.bin/vite\n"
            "#33 ERROR: executor failed running [/bin/sh -c npm run build]: exit code: 1\n"
            "failed to solve: executor failed running [/bin/sh -c npm run build]: exit code: 1\n"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "functional"
    assert v.matched_signature is None


# ---------------------------------------------------------------------------
# V5 / V6 — env.oom: host CONSTRAINT_NONE vs own-cgroup CONSTRAINT_MEMCG
# ---------------------------------------------------------------------------


def test_V5_oom_host_constraint_none_is_env():
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr="#21 8.3 Killed\nERROR: executor failed running [/bin/sh -c npm ci]: exit code: 137\n",
        dmesg_recent=(
            "[12345.678] Out of memory: Killed process 9876 (npm) total-vm:..., "
            "oom-kill:constraint=CONSTRAINT_NONE,nodemask=(null),cpuset=/,mems_allowed=0,...\n"
        ),
        app_has_mem_limit=False,
        # R2 round-13 by-construction precondition: symmetric injection
        # must be active for env.oom to be admissible (without it dmesg
        # CONSTRAINT_NONE collapses self-leak vs co-tenant pressure into
        # one ambiguous signal). The simple_blog spike runner now injects
        # 2g on every app container by default.
        runner_injected_mem_limit="2g",
    )
    v = classify(ctx)
    assert v.verdict == "env"
    assert v.matched_signature == "env.oom"


def test_V6_star_oom_own_cgroup_constraint_memcg_is_functional():
    """★ launder trap: app-cgroup OOM (the app's own memory bug) must NOT be env."""
    ctx = FailureContext(
        phase_reached="app_runtime",
        raw_evidence="docker inspect: State.OOMKilled=true, ExitCode=137",
        dmesg_recent=(
            "[12345.678] Memory cgroup out of memory: Killed process 8765 (node), "
            "oom-kill:constraint=CONSTRAINT_MEMCG,nodemask=(null),"
            "oom_memcg=/docker/abc123,mems_allowed=0,...\n"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "functional"
    assert v.matched_signature is None


def test_V6b_star_oom_app_has_mem_limit_is_functional():
    """Alternative own-cgroup detection: app declared mem_limit in compose."""
    ctx = FailureContext(
        phase_reached="app_runtime",
        raw_evidence="Killed (OOMKilled=true)",
        app_has_mem_limit=True,
    )
    v = classify(ctx)
    assert v.verdict == "functional"


# ---------------------------------------------------------------------------
# V7 / V8 / V9 — env.port_conflict: ephemeral admissibility + retry-success
# ---------------------------------------------------------------------------


def test_V7_port_conflict_ephemeral_foreign_holder_retry_success_is_env():
    ctx = FailureContext(
        phase_reached="infra_setup",
        up_stderr=(
            "Error response from daemon: driver failed programming external connectivity "
            "on endpoint blog-backend: Bind for 0.0.0.0:49231 failed: port is already allocated\n"
        ),
        injected_port=49231,
        foreign_holder_found=True,
        reassign_retry_success=True,
        retry_count=1,
    )
    v = classify(ctx)
    assert v.verdict == "env"
    assert v.matched_signature == "env.port_conflict"
    assert v.retry_count == 1


def test_V8_star_port_conflict_second_collision_on_free_port_is_functional():
    """★ launder trap: a verified-free port can't be pre-owned, so a second
    collision is the app's own bug."""
    ctx = FailureContext(
        phase_reached="infra_setup",
        up_stderr="Bind for 0.0.0.0:49232 failed: port is already allocated\n",
        injected_port=49232,
        foreign_holder_found=True,
        reassign_retry_success=False,
        second_collision_on_free_port=True,
        retry_count=1,
    )
    v = classify(ctx)
    assert v.verdict == "functional"


def test_V9_star_port_conflict_static_port_is_INADMISSIBLE_functional():
    """★ launder trap: static port 8003 (spike's pre-fix shape) is INADMISSIBLE
    for env.port_conflict because we can't prove the runner injected an
    ephemeral port."""
    ctx = FailureContext(
        phase_reached="infra_setup",
        up_stderr="Bind for 0.0.0.0:8003 failed: port is already allocated\n",
        injected_port=8003,  # < EPHEMERAL_FLOOR → INADMISSIBLE.
        foreign_holder_found=True,
        reassign_retry_success=True,
    )
    v = classify(ctx)
    assert v.verdict == "functional"


# ---------------------------------------------------------------------------
# V10 / V11 / V12 — env.daemon_down: live-probe guard + deadline neg-guard
# ---------------------------------------------------------------------------


def test_V10_daemon_down_with_3x_live_probe_failures_is_env():
    # R1 round-14: V10 now requires daemon_up_at_failure_time=False explicitly
    # (matching real runner behavior — runner captures the T+0 systemctl probe
    # on subprocess.run failure SYNCHRONOUSLY before any retries). The legacy
    # "3x retries all-fail → env" fallback was removed (round-4 finding: on a
    # CI host without systemctl, 3 transient blips would silently inflate as
    # env.daemon_down with no T+0 proof). docker_version_retries remains as
    # corroborating evidence in negative_guard_evidence — never as a gate.
    ctx = FailureContext(
        phase_reached="infra_setup",
        up_stderr=(
            "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. "
            "Is the docker daemon running?\n"
        ),
        docker_version_retries=[(1, "Cannot connect"), (1, "Cannot connect"), (1, "Cannot connect")],
        daemon_up_at_failure_time=False,  # synchronous T+0 systemctl probe
    )
    v = classify(ctx)
    assert v.verdict == "env"
    assert v.matched_signature == "env.daemon_down"


def test_V11_star_context_deadline_during_long_run_is_functional():
    """★ launder trap: a long RUN step that hits context deadline is app-fault
    (the app's own RUN took too long), not daemon down."""
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr=(
            "#7 600.0 error during connect: Post \"http://%2Fvar%2Frun%2Fdocker.sock/...\": "
            "context deadline exceeded\n"
            "#7 ERROR: executor failed running [/bin/sh -c npm install]: context deadline exceeded\n"
        ),
        docker_version_retries=[(1, "")],  # spurious; the neg-guard fires first.
    )
    v = classify(ctx)
    assert v.verdict == "functional"


def test_V12_star_daemon_down_with_healed_blip_is_functional():
    """★ launder trap: the daemon error appears, but a live `docker version`
    probe succeeds → it was a transient blip, not persistent down."""
    ctx = FailureContext(
        phase_reached="infra_setup",
        up_stderr="Cannot connect to the Docker daemon at unix://...\n",
        docker_version_retries=[(1, "fail"), (0, "Docker version 20.10.8")],
    )
    v = classify(ctx)
    assert v.verdict == "functional"


def test_V_round5_daemon_down_no_T0_probe_retries_all_fail_is_functional():
    """★ R1 round-14 launder trap (round-4 finding): on a CI host with no
    systemctl (so `daemon_up_at_failure_time` is None — no synchronous T+0
    measurement available) plus three transient `docker version` retries
    that ALL fail post-hoc, the prior back-compat / legacy / transitional
    sentinel path silently inflated this as env.daemon_down. That violated:
      (a) spec §3 row 228 — `daemon_up_at_failure_time == False` is a
          hard AND-conjunct, NOT a fallback; and
      (b) spec §3 prereq #5 — "Post-hoc docker version retries are
          corroborating evidence only, never gating."
    Round-13 closed the hole; this fixture pins the new behavior. Without
    a T+0 probe proving the daemon was DOWN at the moment of failure, the
    only safe verdict is FUNCTIONAL (conservative default).
    """
    ctx = FailureContext(
        phase_reached="infra_setup",
        up_stderr=(
            "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. "
            "Is the docker daemon running?\n"
        ),
        daemon_up_at_failure_time=None,  # no synchronous T+0 measurement available
        docker_version_retries=[(1, "fail"), (1, "fail"), (1, "fail")],
    )
    v = classify(ctx)
    assert v.verdict == "functional"
    assert v.matched_signature is None


# ---------------------------------------------------------------------------
# V13 / V14 / V15 — env.disk_full: storage-driver path is the only env case
# ---------------------------------------------------------------------------


def test_V13_star_pip_RUN_step_ENOSPC_is_functional():
    """★ launder trap: ENOSPC inside a RUN step = the app's runaway/bloated
    dependencies, not host disk full."""
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr=(
            "#7 12.34   File \"/usr/lib/python3.11/shutil.py\", line ..., in copyfile\n"
            "#7 12.34     raise OSError(28, 'No space left on device') from None\n"
            "#7 12.34 OSError: [Errno 28] No space left on device\n"
            "#7 ERROR: executor failed running [/bin/sh -c pip install -r requirements.txt]: exit code: 1\n"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "functional"


def test_V14_disk_full_storage_driver_path_is_env():
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr=(
            "failed to register layer: write /var/lib/docker/overlay2/abc/diff/...: "
            "no space left on device\n"
        ),
        df_var_lib_docker="/dev/sda2  1.8T  1.8T  0  100% /var/lib/docker",
    )
    v = classify(ctx)
    assert v.verdict == "env"
    assert v.matched_signature == "env.disk_full"


def test_V15_star_vite_file_watcher_limit_is_functional():
    """★ launder trap: inotify watcher exhaustion is an app config issue
    (vite/chokidar opening too many watchers), not host disk."""
    ctx = FailureContext(
        phase_reached="app_runtime",
        raw_evidence=(
            "ENOSPC: System limit for number of file watchers reached, watch '/app/src'\n"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "functional"


# ---------------------------------------------------------------------------
# V16 — step-0 invariant: oracle <failure> is ALWAYS functional
# ---------------------------------------------------------------------------


def test_V16_oracle_junit_failure_is_step_0_functional():
    ctx = FailureContext(
        phase_reached="oracle",
        junit_failure_text=(
            "AssertionError: expected 401 got 201\n"
            "  at assert_unauthorized(response)\n"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "functional"
    # Even if env signatures could theoretically match, step-0 wins.


def test_V16b_oracle_junit_failure_beats_env_signatures():
    """Reinforcement: a <failure> with concurrent env-looking evidence still wins
    for FUNCTIONAL — the flow-assertion is the signal."""
    ctx = FailureContext(
        phase_reached="oracle",
        junit_failure_text="AssertionError: items missing from listing",
        raw_evidence="Cannot connect to the Docker daemon",  # would otherwise fire env.daemon_down
        docker_version_retries=[(1, "fail")] * 3,
    )
    v = classify(ctx)
    assert v.verdict == "functional"


# ---------------------------------------------------------------------------
# V19 / V20 — env.buildkit_recurrence apt variant: Fetched-proof + DNS-neg
# ---------------------------------------------------------------------------


def test_V19_apt_post_invoke_with_fetched_proof_is_env():
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr=(
            "#5 0.8 Get:1 http://deb.debian.org/debian bookworm InRelease [151 kB]\n"
            "#5 1.2 Fetched 24.3 MB in 0s (50 MB/s)\n"
            "#5 1.5 E: Problem executing scripts APT::Update::Post-Invoke "
            "'rm -f /var/cache/apt/archives/*.deb || true'\n"
            "#5 1.5 fork: Cannot allocate memory\n"
            "#5 ERROR: executor failed running [/bin/sh -c apt-get update]: exit code: 100\n"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "env"
    assert v.matched_signature == "env.buildkit_recurrence"


def test_V20_star_apt_dns_failure_is_functional():
    """★ launder trap: apt-get can't resolve a mirror (DNS) — NOT the BuildKit
    recurrence pattern. Could be ad-hoc app misconfig of /etc/resolv.conf."""
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr=(
            "#5 W: Could not resolve 'archive.ubuntu.com'\n"
            "#5 E: Failed to fetch http://archive.ubuntu.com/ubuntu/dists/jammy/InRelease\n"
            "#5 ERROR: executor failed running [/bin/sh -c apt-get update]: exit code: 100\n"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "functional"


# ---------------------------------------------------------------------------
# V21 / V22 / V23 — env.image_pull: base-registry transient vs content
# ---------------------------------------------------------------------------


def test_V21_base_registry_TLS_timeout_is_env():
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr=(
            "failed to do request: Head \"https://registry-1.docker.io/v2/library/node/manifests/20-alpine\": "
            "net/http: TLS handshake timeout\n"
            "ERROR: executor failed running [/bin/sh -c ...]\n"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "env"
    assert v.matched_signature == "env.image_pull"


def test_V22_star_npm_registry_404_is_functional():
    """★ launder trap: npm package not found = the app's package.json names a
    nonexistent package. Content failure, B2 vector."""
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr=(
            "#7 1.2 npm ERR! 404 Not Found - GET https://registry.npmjs.org/leftpad-typo\n"
            "#7 1.2 npm ERR! 404 'leftpad-typo@*' is not in this registry.\n"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "functional"


def test_V23_star_manifest_unknown_is_functional():
    """★ launder trap: image tag doesn't exist (e.g. FROM ghcr.io/fake/img:v999) =
    the app's Dockerfile names a nonexistent image. Content failure."""
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr=(
            "manifest unknown: manifest unknown for ghcr.io/some/image:v999.0\n"
            "pull access denied for ghcr.io/some/image\n"
            "ERROR: failed to solve: pull access denied\n"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "functional"


# ---------------------------------------------------------------------------
# V24 / V25 — env.oracle_infra: control-group reproduction required
# ---------------------------------------------------------------------------


def test_V24_oracle_code_crash_reproduces_on_control_is_env():
    ctx = FailureContext(
        phase_reached="oracle",
        junit_error_text=(
            "Traceback (most recent call last):\n"
            "  File \"/agent/tests/north_star/_conventions.py\", line 88, in authenticate\n"
            "    raise AttributeError(\"NoneType has no attribute 'token'\")\n"
        ),
        reproduces_against_reference_impl=True,
    )
    v = classify(ctx)
    assert v.verdict == "env"
    assert v.matched_signature == "env.oracle_infra"


def test_V25_star_playwright_launch_app_triggered_is_functional():
    """★ launder trap: Playwright sandbox failure that ONLY appears against the
    app-under-test (not the control) is app-triggered = functional."""
    ctx = FailureContext(
        phase_reached="oracle",
        junit_error_text=(
            "playwright._impl._errors.Error: BrowserType.launch: No usable sandbox!\n"
            "  at /app/oracle/test_view_post.py:42\n"
        ),
        reproduces_against_reference_impl=False,
    )
    v = classify(ctx)
    assert v.verdict == "functional"


# ---------------------------------------------------------------------------
# Smoke positive: jira-web db + backend came up
# ---------------------------------------------------------------------------


def test_jira_db_smoke_pass_default_classifier_not_called_on_pass():
    """A passing run never reaches the classifier (it's invoked only on failure).
    Asserting here is a documentation reminder: classifier is for FAILED runs."""
    # No call to classify(); this test exists to pin the documented expectation.
    assert True


# ---------------------------------------------------------------------------
# [POPULATE] — real round-11 smoke pre-fix spike failures (per §7 gate)
# ---------------------------------------------------------------------------


def test_V26_populate_round11_spike_arm2_uv_thread_create_is_env():
    """[POPULATE] Round-11 spike arm_2 stderr: target_impl_broken (when it
    was express-only — pre-Q2 fix) failed with node's uv_thread_create
    assertion under BuildKit. Tests env.buildkit_recurrence variant 3
    (node uv_thread_create + npm/node RUN context)."""
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr=(
            "#8 0.336 #  node[7]: ../src/node_platform.cc:68: void node::WorkerThreadsTaskRunner"
            "::DelayedTaskScheduler::Start(): Assertion `(0) == (uv_thread_create(t.get(), "
            "start_thread, this))' failed.\n"
            "#8 0.336 #  Assertion failed: (0) == (uv_thread_create(t.get(), start_thread, this))\n"
            "#8 0.484 Aborted (core dumped)\n"
            "#8 ERROR: executor failed running [/bin/sh -c npm install]: exit code: 134\n"
            "failed to solve: executor failed running [/bin/sh -c npm install]: exit code: 134\n"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "env"
    assert v.matched_signature == "env.buildkit_recurrence"


def test_V27_populate_round11_airbnb_postgres_date_bigint_is_functional():
    """[POPULATE] Round-11 spike arm_3 airbnb fixture: postgres exited code 3
    because 02_seed.sql:70 had `DATE + bigint` with no operator. This is a
    seed-SQL CONTENT bug — must be classified FUNCTIONAL, NOT env. (Fix
    landed at commit 67ecb385 in B2; this fixture pins the classification
    so a future regression of the seed bug would correctly count against
    the airbnb fixture, not be quietly excluded.)"""
    ctx = FailureContext(
        phase_reached="app_runtime",
        raw_evidence=(
            "psql:/docker-entrypoint-initdb.d/02_seed.sql:73: ERROR:  operator does not exist: date + bigint\n"
            "LINE 8:        (DATE '2016-01-01' + ((row_number() OVER (ORDER BY u....\n"
            "HINT:  No operator matches the given name and argument types. You might need to add explicit type casts.\n"
            "container docker-database-1 exited (3)\n"
            "dependency failed to start: container docker-database-1 exited (3)\n"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "functional"
    assert v.matched_signature is None


def test_V28_populate_round11_spike_arm_1a_pip_rich_thread():
    """[POPULATE] Round-11 spike arm_1a stderr: reference_impl pip install
    of fastapi/uvicorn/pydantic failed with rich progress-bar thread
    crash. Same shape as V1 but pulled from the actual spike honest-
    signal log so we can prove the classifier reproduces the real-data
    label, not just synthetic fixtures."""
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr=(
            "#9 2.892   File \"/usr/local/lib/python3.11/site-packages/pip/_vendor/rich/progress.py\", line ..., in start\n"
            "#9 2.892   File \"/usr/local/lib/python3.11/site-packages/pip/_vendor/rich/live.py\", line 116, in start\n"
            "#9 2.892     self._refresh_thread.start()\n"
            "#9 2.892   File \"/usr/local/lib/python3.11/threading.py\", line 964, in start\n"
            "#9 2.892     _start_new_thread(self._bootstrap, ())\n"
            "#9 2.892 RuntimeError: can't start new thread\n"
            "#9 3.002 [notice] A new release of pip is available: 24.0 -> 26.1.1\n"
            "#9 ERROR: executor failed running [/bin/sh -c pip install --no-cache-dir -r requirements.txt]: exit code: 2\n"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "env"
    assert v.matched_signature == "env.buildkit_recurrence"


# ---------------------------------------------------------------------------
# Terminal-default coverage: unmatched failure → FUNCTIONAL
# ---------------------------------------------------------------------------


def test_terminal_default_unmatched_failure_is_functional():
    ctx = FailureContext(
        phase_reached="app_runtime",
        raw_evidence="The app crashed: TypeError: undefined is not a function\n",
    )
    v = classify(ctx)
    assert v.verdict == "functional"
    assert v.matched_signature is None
    assert "terminal default" in (v.negative_guard_evidence or "").lower()


def test_unmatched_evidence_carries_spec_sha():
    ctx = FailureContext(raw_evidence="anything")
    v = classify(ctx)
    assert v.classifier_spec_sha  # non-empty pin


# ---------------------------------------------------------------------------
# R1 round-12 remediation fixtures (D1-D5).
# Every fixture below is a star-launder-trap pinning a specific over-exclude
# vector found in the round-12 R1 sweep. The previous (pre-fix) classifier
# would have mis-classified these as env; this commit pins them FUNCTIONAL.
# ---------------------------------------------------------------------------


# --- D1: env.daemon_down channel + window-probe fixes ---------------------


def test_V29_D1_star_daemon_down_token_in_raw_evidence_only_is_functional():
    """★ Channel-provenance: the daemon-connect string is in raw_evidence
    (= `docker compose logs` app output), NOT in transport stderr. With the
    round-12 channel restriction the positive regex never sees it; even if it
    did, the new `Error response from daemon:` negative guard would block."""
    ctx = FailureContext(
        phase_reached="app_runtime",
        up_stderr="",
        build_stderr="",
        raw_evidence=(
            "Error response from daemon: 500 Internal Server Error: "
            "Cannot connect to the Docker daemon at unix:///var/run/docker.sock\n"
        ),
        docker_version_retries=[(1, "transient blip")],
        daemon_up_at_failure_time=True,
    )
    v = classify(ctx)
    assert v.verdict == "functional"
    assert v.matched_signature is None


def test_V30_D1_star_daemon_down_post_hoc_blip_with_window_up_is_functional():
    """★ Post-hoc-retries vs T+0 window: all three docker-version retries say
    `down` but the synchronous T+0 probe says the daemon WAS up during the
    failure window. The post-hoc blip cannot launder a healed hiccup."""
    ctx = FailureContext(
        phase_reached="infra_setup",
        up_stderr=(
            "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. "
            "Is the docker daemon running?\n"
        ),
        docker_version_retries=[
            (1, "Cannot connect"),
            (1, "Cannot connect"),
            (1, "Cannot connect"),
        ],
        daemon_up_at_failure_time=True,
    )
    v = classify(ctx)
    assert v.verdict == "functional"
    assert v.matched_signature is None


def test_V30b_D1_daemon_down_window_down_at_t0_is_env():
    """Positive control: synchronous probe says down at T+0 → env.daemon_down."""
    ctx = FailureContext(
        phase_reached="infra_setup",
        up_stderr=(
            "Cannot connect to the Docker daemon at unix:///var/run/docker.sock\n"
        ),
        docker_version_retries=[(1, "Cannot connect"), (1, "Cannot connect"), (1, "Cannot connect")],
        daemon_up_at_failure_time=False,
    )
    v = classify(ctx)
    assert v.verdict == "env"
    assert v.matched_signature == "env.daemon_down"


def test_V31_D1_star_step_0_empty_failure_body_is_functional():
    """★ Element-presence (B-7): an empty <failure/> body must STILL trigger
    step-0 FUNCTIONAL even when co-occurring with what would otherwise be
    host-OOM dmesg evidence."""
    ctx = FailureContext(
        phase_reached="oracle",
        junit_failure_text="",  # empty body — element exists per xUnit self-close
        raw_evidence="",
        dmesg_recent="oom-kill: ... constraint=CONSTRAINT_NONE ...",
    )
    v = classify(ctx)
    assert v.verdict == "functional"
    assert "step-0" in (v.negative_guard_evidence or "").lower()


def test_V32_D1_step_0_None_falls_through_to_env_oom():
    """Symmetric guard for V31: junit_failure_text=None (no element at all)
    must NOT trigger step-0; env.oom can then fire normally.

    R1 round-13 update: positive '137 / Killed' tokens moved from
    raw_evidence (= app stdout/compose-logs; now excluded by channel-
    provenance gate) into up_stderr (= docker CLI transport — the
    container-exit channel). R2 round-13 update: runner_injected_mem_limit
    set to '2g' so the by-construction precondition is satisfied.
    """
    ctx = FailureContext(
        phase_reached="app_runtime",
        junit_failure_text=None,
        up_stderr="service_app_1 exited with code 137\nKilled\n",
        raw_evidence="",
        dmesg_recent="oom-kill: ... constraint=CONSTRAINT_NONE ...",
        app_has_mem_limit=False,
        runner_injected_mem_limit="2g",
    )
    v = classify(ctx)
    assert v.verdict == "env"
    assert v.matched_signature == "env.oom"


# --- D2: env.image_pull negative-guard extension + buildkit node tighten ---


def test_V29_D2_star_image_pull_tag_not_found_is_functional():
    """★ Tag-not-found is functional. The `:vfake: not found` form must veto
    even when a transient token is also present."""
    stderr = (
        "#8 0.532 failed to solve: ghcr.io/foo/bar:vfake: not found\n"
        "#8 0.534 dial tcp 140.82.114.34:443: i/o timeout\n"
    )
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr=stderr,
    )
    v = classify(ctx)
    assert v.verdict == "functional"
    assert v.matched_signature is None


def test_V30_D2_star_image_pull_insufficient_scope_is_functional():
    """★ OCI auth content failure: `insufficient_scope` vetoes even with a
    ghcr.io + i/o timeout transient line co-present."""
    stderr = (
        "#7 ERROR: failed to authorize: failed to fetch oauth token: "
        "unexpected status from POST request to https://ghcr.io/token: 403 Forbidden\n"
        "#7 0.123 dial tcp 140.82.114.34:443: i/o timeout\n"
        "#7 0.124 ghcr.io insufficient_scope: authorization failed\n"
    )
    ctx = FailureContext(phase_reached="app_build", build_stderr=stderr)
    v = classify(ctx)
    assert v.verdict == "functional"
    assert v.matched_signature is None


def test_V31_D2_star_image_pull_403_denied_is_functional():
    """★ Bare HTTP 403 + denied is registry permission denial (functional)."""
    stderr = (
        "#5 ERROR: pulling from host ghcr.io failed with status 403 Forbidden\n"
        "#5 0.456 dial tcp 140.82.114.34:443: connection refused\n"
        "#5 0.457 denied: requested access to the resource is denied\n"
    )
    ctx = FailureContext(phase_reached="app_build", build_stderr=stderr)
    v = classify(ctx)
    assert v.verdict == "functional"
    assert v.matched_signature is None


def test_V32_D2_star_buildkit_node_no_sigabrt_is_functional():
    """★ Node variant tightened: uv_thread_create text but no SIGABRT and no
    RUN-step npm/node prefix → must NOT classify as env.buildkit_recurrence."""
    stderr = (
        "#9 12.345 Assertion failed: (0) == (uv_thread_create(&worker, w, NULL)), "
        "function uv__work_submit, file ../deps/uv/src/threadpool.c, line 305.\n"
        "#9 12.346 internal compiler note: thread pool exhausted\n"
    )
    ctx = FailureContext(phase_reached="app_build", build_stderr=stderr)
    v = classify(ctx)
    assert v.verdict == "functional"


def test_V33_D2_star_buildkit_node_app_traceback_only_is_functional():
    """★ App's own traceback contains uv_thread_create + Aborted + exit 134 +
    'node'/'npm' — but it's in raw_evidence (app output), not in a BuildKit
    RUN-step prefix. _NPM_NODE_RUN_STEP requires the `#N M.MM` prefix shape."""
    raw_ev = (
        "app log: /usr/src/app/node_modules/foo/dist/index.js:42\n"
        "    throw new Error('Assertion failed: (0) == (uv_thread_create(&w, fn, NULL)) "
        "reproduced in user code')\n"
        "    at runNpmTask (/usr/src/app/scripts/start.js:10:5)\n"
        "  Aborted (core dumped)\n"
        "[app] exit 134\n"
    )
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr="",
        raw_evidence=raw_ev,
    )
    v = classify(ctx)
    # Without a BuildKit `#N M.MM ... npm/node` line, variant-3 must not fire.
    assert v.verdict == "functional"


def test_V34_D2_star_daemon_5xx_deleted_app_500_is_functional():
    """★ env.daemon_5xx deleted in R1 round-12: an app that prints a 500 +
    /var/run/docker.sock string must classify as terminal-default FUNCTIONAL."""
    ctx = FailureContext(
        phase_reached="app_runtime",
        raw_evidence=(
            "app reverse-proxy log: upstream returned 500 Internal Server Error "
            "from /var/run/docker.sock during admin probe\n"
            "[proxy] dockerd panic message echoed by user code\n"
        ),
        build_stderr="",
        up_stderr="",
    )
    v = classify(ctx)
    assert v.verdict == "functional"
    assert v.matched_signature is None


# --- D3: own-cgroup OOMKilled + disk_full df-corroboration + channel -------


def test_V29_D3_star_oom_OOMKilled_true_is_functional():
    """★ docker inspect State.OOMKilled=True is the daemon's authoritative
    statement that THIS container hit its cgroup OOM. Even if host dmesg
    shows CONSTRAINT_NONE (coincident neighbor OOM), OOMKilled wins."""
    ctx = FailureContext(
        phase_reached="app_runtime",
        raw_evidence="myapp exited with code 137 Killed",
        up_stderr="",
        build_stderr="",
        docker_inspect_state={"Status": "exited", "ExitCode": 137, "OOMKilled": True},
        dmesg_recent="oom-kill: ... constraint=CONSTRAINT_NONE ...",
        app_has_mem_limit=False,
    )
    v = classify(ctx)
    assert v.verdict == "functional"


def test_V31_D3_star_disk_full_no_df_corroboration_is_functional():
    """★ storage-driver ENOSPC string present but df shows only 30% used →
    no corroboration → unverified → FUNCTIONAL default."""
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr=(
            "failed to register layer: write /var/lib/docker/overlay2/abc/diff/...: "
            "no space left on device\n"
        ),
        df_var_lib_docker=(
            "Filesystem 1K-blocks Used Avail Capacity Mounted-on\n"
            "/dev/sda1   100000   30000 70000   30%    /var/lib/docker\n"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "functional"


def test_V32_D3_star_disk_full_tar_app_path_is_functional():
    """★ `Error processing tar file ... no space left on device` writing to
    /app/dist (app content) — even with df at 95% — must classify FUNCTIONAL
    because the tar arm requires /var/lib/docker/ co-location in the same line."""
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr=(
            "Step 5/8 : RUN tar -czf /app/dist.tgz /app/dist\n"
            " ---> Error processing tar file: no space left on device while "
            "writing /app/dist/build.tgz\n"
        ),
        df_var_lib_docker=(
            "Filesystem  ... 95% /var/lib/docker\n"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "functional"


def test_V33_D3_star_disk_full_RUN_step_steals_precedence_over_storage_driver():
    """★ Both RUN-step Errno 28 AND storage-driver ENOSPC present + df at 95%.
    RUN-step is the precedence-stealer: app caused the layer bloat."""
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr=(
            "#7 12.34 OSError: [Errno 28] No space left on device: /app/node_modules/.cache\n"
            "#7 ERROR: process \"/bin/sh -c npm install\" did not complete successfully\n"
            "failed to register layer: write /var/lib/docker/overlay2/xyz/diff: "
            "no space left on device\n"
        ),
        df_var_lib_docker="Filesystem ... 95% /var/lib/docker\n",
    )
    v = classify(ctx)
    assert v.verdict == "functional"


def test_V35_D3_star_channel_provenance_app_daemon_string_in_raw_evidence():
    """★ Channel-provenance: app's RUN-step prints a daemon-down-shaped
    string in build STDOUT (= raw_evidence under the new runner contract).
    The transport-stderr-only matching defeats this launder."""
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr="#5 0.234 npm ERR! Cannot find module foo\n",
        raw_evidence=(
            "Cannot connect to the Docker daemon at unix:///var/run/docker.sock"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "functional"
    assert v.matched_signature is None


# --- D5: port_conflict positive must name P literally + meta sweeps -------


def test_V29_D5_star_port_conflict_substring_without_P_is_functional():
    """★ Up-stderr names port 50001 with `port is already allocated`, but the
    runner injected 49231. Bare-substring positive must NOT match a different
    port — even when foreign_holder_found=True + reassign_retry_success=True."""
    ctx = FailureContext(
        phase_reached="infra_setup",
        up_stderr=(
            "Error response from daemon: driver failed programming external "
            "connectivity on endpoint x: Bind for 0.0.0.0:50001 failed: "
            "port is already allocated\n"
        ),
        injected_port=49231,
        foreign_holder_found=True,
        reassign_retry_success=True,
    )
    v = classify(ctx)
    assert v.verdict == "functional"


def test_V30_D5_port_conflict_foreign_holder_none_is_functional():
    """Regression fence: when runner does not populate foreign_holder_found
    (still default None), the classifier must NOT fire env.port_conflict
    even if the literal port and a positive token are present."""
    ctx = FailureContext(
        phase_reached="infra_setup",
        up_stderr="Bind for 0.0.0.0:49231 failed: port is already allocated\n",
        injected_port=49231,
        foreign_holder_found=None,
        reassign_retry_success=None,
    )
    v = classify(ctx)
    assert v.verdict == "functional"


def test_V31_D5_port_conflict_second_collision_on_free_port_is_functional():
    """Once runner populates the structured fields, V8's second-collision
    branch must short-circuit to FUNCTIONAL even with foreign_holder_found=True."""
    ctx = FailureContext(
        phase_reached="infra_setup",
        up_stderr="Bind for 0.0.0.0:49231 failed: port is already allocated\n",
        injected_port=49231,
        foreign_holder_found=True,
        reassign_retry_success=False,
        second_collision_on_free_port=True,
    )
    v = classify(ctx)
    assert v.verdict == "functional"


def test_V36_D5_star_daemon_5xx_in_raw_evidence_only_is_functional():
    """★ env.daemon_5xx deletion is robust against the residual fixture
    shape: 500 in raw_evidence only, transport stderr clean → terminal
    FUNCTIONAL."""
    ctx = FailureContext(
        phase_reached="app_runtime",
        raw_evidence=(
            "docker daemon API call returned 500 Internal Server Error from "
            "app's reverse-proxy logging the underlying upstream"
        ),
        up_stderr="",
        build_stderr="",
    )
    v = classify(ctx)
    assert v.verdict == "functional"


# --- B-8: schema-shape coverage -------------------------------------------


SPEC_SECTION_2_FIELDS = {
    "run_id",
    "spec_id",
    "arm",
    "phase_reached",
    "outcome",
    "verdict",
    "matched_signature",
    "raw_evidence",
    "negative_guard_evidence",
    "retry_count",
    "classifier_spec_sha",
}


def test_V31_B8_verdict_to_dict_matches_spec_section_2_schema():
    """Verdict.to_dict() emits exactly the §2 schema keys (B-8 freeze guard)."""
    v = Verdict(
        verdict="env",
        run_id="x",
        spec_id="simple_blog",
        arm="ab_new",
        phase_reached="app_build",
        outcome="fail",
        matched_signature="env.oom",
        raw_evidence="e",
        negative_guard_evidence="g",
    )
    assert set(v.to_dict().keys()) == SPEC_SECTION_2_FIELDS


def test_classify_populates_section_2_fields_from_context():
    """classify() copies §2 fields from FailureContext into Verdict (B-8)."""
    ctx = FailureContext(
        run_id="rid-1",
        spec_id="simple_blog",
        arm="ab_new",
        phase_reached="app_build",
        outcome="fail",
        build_stderr="some unmatched error",
    )
    v = classify(ctx)
    d = v.to_dict()
    assert d["run_id"] == "rid-1"
    assert d["spec_id"] == "simple_blog"
    assert d["arm"] == "ab_new"
    assert d["phase_reached"] == "app_build"
    assert d["outcome"] == "fail"
    assert set(d.keys()) == SPEC_SECTION_2_FIELDS


# ---------------------------------------------------------------------------
# R2 round-2 blocker fixtures (B-2 / B-5 positive tightening).
# Each ★ trap below is an adversarial PoC the round-1 R1 sweep would have
# missed because the positive matchers fired on any line shape containing the
# relevant tokens. The two control fixtures pin that the tightened matchers
# still recognize REAL dockerd-transport / BuildKit-RUN failures.
# ---------------------------------------------------------------------------


def test_V_blocker_round2_buildkit_node_app_preflight_run_step_is_functional():
    """★ B-5 launder trap: an app preflight script (bash scripts/preflight.sh)
    prints `node v20.0.0 OK` on a BuildKit-prefixed stdout line, then an
    internal assertion abort fires inside the script's own toolchain check.
    The pre-tightening regex matched on `node` anywhere in a `#N M.M ...` line
    → over-excluded as env. With the tightened `_NPM_NODE_RUN_STEP` (line must
    BE the docker CLI RUN command echo OR the BuildKit ERROR wrapper naming a
    node/npm/yarn/pnpm command), this PoC stays FUNCTIONAL.
    """
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr=(
            "#8 0.10 [scripts/preflight.sh] checking that node is installed\n"
            "#8 0.20 node v20.0.0 OK\n"
            "#8 0.40 Assertion failed: (0) == (uv_thread_create(&w, fn, NULL))\n"
            "#8 0.41 Aborted (core dumped)\n"
            '#8 ERROR: process "/bin/sh -c bash scripts/preflight.sh" did not complete successfully: exit code: 134\n'
        ),
    )
    v = classify(ctx)
    assert v.verdict == "functional"
    assert v.matched_signature is None


def test_V_blocker_round2_image_pull_app_run_step_curl_timeout_is_functional():
    """★ B-2 launder trap: an app's RUN-step shells out to `wget` against the
    docker-hub registry host and hits an i/o timeout. The line carries the
    registry host + transient token, but NO dockerd/containerd/BuildKit
    image-pull subsystem markers appear in the buffer — the failure is at
    the app's curl/wget, not dockerd's image-pull transport. With the
    tightened `_IMAGE_PULL_DOCKERD_MARKER` gate, this PoC stays FUNCTIONAL.
    """
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr=(
            "#5 1.0 + wget https://registry-1.docker.io/v2/_catalog\n"
            "#5 1.2 wget: dial tcp registry-1.docker.io: i/o timeout\n"
            '#5 ERROR: process "/bin/sh -c wget registry-1.docker.io/v2/_catalog" did not complete successfully: exit code: 1\n'
        ),
    )
    v = classify(ctx)
    assert v.verdict == "functional"
    assert v.matched_signature is None


def test_V_blocker_round2_image_pull_real_dockerd_transport_timeout_is_env():
    """Positive control for B-2: a REAL dockerd image-pull transport timeout
    carries the `failed to do request:` dockerd marker AND the registry host
    + TLS handshake timeout transient. The tightened matcher must still
    classify this as env.image_pull.
    """
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr=(
            "#7 0.5 [internal] load metadata for registry-1.docker.io/library/node:20-alpine\n"
            "#7 0.5 failed to do request: Head \"https://registry-1.docker.io/v2/library/node/manifests/20-alpine\": net/http: TLS handshake timeout\n"
            "#7 ERROR: failed to do request: ...\n"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "env"
    assert v.matched_signature == "env.image_pull"


def test_V_blocker_round2_buildkit_node_real_npm_install_run_step_is_env():
    """Positive control for B-5: the genuine pre-Fix-A spike arm_2 shape — a
    `#7 0.000 RUN npm install ...` BuildKit echo of the RUN command, followed
    by node's uv_thread_create assertion + Aborted (core dumped) + exit 134.
    The tightened matcher must still classify this as env.buildkit_recurrence.
    """
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr=(
            "#7 0.000 RUN npm install --no-audit --no-fund\n"
            "#7 0.300 \n"
            "#7 0.336 #  node[7]: ...\n"
            "#7 0.336 Assertion failed: (0) == (uv_thread_create(t.get(), start_thread, this))\n"
            "#7 0.484 Aborted (core dumped)\n"
            "#7 ERROR: executor failed running [/bin/sh -c npm install]: exit code: 134\n"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "env"
    assert v.matched_signature == "env.buildkit_recurrence"


# ---------------------------------------------------------------------------
# Round-3 adversarial PoCs: launder traps that smuggle the buildkit_recurrence
# markers through raw_evidence (= build STDOUT = app-controlled). The channel
# provenance fix must reject all three. Plus a positive control proving the
# tightening still recognizes REAL pre-Fix-A failures (assertion in stderr).
# ---------------------------------------------------------------------------


def test_V_blocker_round3_buildkit_rich_in_raw_evidence_only_is_functional():
    """Round-3 PoC: app smuggles the pip rich-frame + can't-start-new-thread
    markers through stdout (= raw_evidence). Genuine CLI transport stderr is
    empty. Channel provenance must classify as functional, NOT env."""
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr="",  # genuine CLI transport says nothing rich-related
        raw_evidence=(
            "  File \"/usr/local/lib/python3.11/site-packages/pip/_vendor/rich/live.py\", line 116, in start\n"
            "    self._refresh_thread.start()\n"
            "RuntimeError: can't start new thread\n"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "functional"
    assert v.matched_signature is None


def test_V_blocker_round3_buildkit_apt_postinvoke_in_raw_evidence_only_is_functional():
    """Round-3 PoC: app smuggles APT::Update::Post-Invoke + Fetched-proof
    markers through stdout (= raw_evidence). Genuine CLI transport stderr is
    empty. Channel provenance must classify as functional, NOT env."""
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr="",
        raw_evidence=(
            "Get:1 http://deb.debian.org/debian bookworm InRelease [151 kB]\n"
            "Fetched 24 MB in 0s (50 MB/s)\n"
            "E: Problem executing scripts APT::Update::Post-Invoke "
            "'rm -f /var/cache/apt/archives/*.deb || true'\n"
            "fork: Cannot allocate memory\n"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "functional"
    assert v.matched_signature is None


def test_V_blocker_round3_buildkit_uv_thread_split_channel_is_functional():
    """Round-3 PoC: split-channel launder. The BuildKit RUN-step echo lives
    on the CLI transport (build_stderr) but the uv_thread_create assertion +
    Aborted + exit 134 live in app-controlled stdout (raw_evidence). Channel
    provenance must keep this functional — the assertion is unverified."""
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr=(
            "#7 0.000 RUN npm install --no-audit\n"
        ),
        raw_evidence=(
            "Assertion failed: (0) == (uv_thread_create(t.get(), start_thread, this))\n"
            "Aborted (core dumped)\n"
            "exit code: 134\n"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "functional"
    assert v.matched_signature is None


def test_V_blocker_round3_buildkit_uv_thread_legitimate_in_build_stderr_is_env():
    """Round-3 positive control: the tightening must NOT regress real
    pre-Fix-A buildkit failures where dockerd echoed the full uv_thread_create
    assertion + Aborted + exit 134 + RUN npm install all on build_stderr."""
    ctx = FailureContext(
        phase_reached="app_build",
        build_stderr=(
            "#7 0.000 RUN npm install --no-audit --no-fund\n"
            "#7 0.336 #  node[7]: ../src/node_platform.cc:68: void node::WorkerThreadsTaskRunner"
            "::DelayedTaskScheduler::Start(): Assertion `(0) == (uv_thread_create(t.get(), "
            "start_thread, this))' failed.\n"
            "#7 0.336 Assertion failed: (0) == (uv_thread_create(t.get(), start_thread, this))\n"
            "#7 0.484 Aborted (core dumped)\n"
            "#7 ERROR: executor failed running [/bin/sh -c npm install]: exit code: 134\n"
            "failed to solve: executor failed running [/bin/sh -c npm install]: exit code: 134\n"
        ),
    )
    v = classify(ctx)
    assert v.verdict == "env"
    assert v.matched_signature == "env.buildkit_recurrence"


# ---------------------------------------------------------------------------
# R1/R2 round-13 env.oom remediation fixtures (D1 + D2 + D3 designs).
# Each ★ trap below is an adversarial PoC against the env.oom signature
# vectors found in the round-13 sweep:
#   - D1: OOMKilled=False must veto env.oom (daemon authority both ways).
#   - D2: positive token from raw_evidence (compose-logs) alone must NOT fire
#         env.oom — channel-provenance restriction now applies.
#   - D3: without runner-injected symmetric mem_limit, host CONSTRAINT_NONE
#         is structurally ambiguous; default → FUNCTIONAL.
# ---------------------------------------------------------------------------


# --- D1: docker daemon's OOMKilled bit is authoritative both ways ----------


def test_V_round4_oom_OOMKilled_False_host_constraint_none_is_functional():
    """★ R1 round-13 D1 launder trap: host has a real CONSTRAINT_NONE OOM
    event in dmesg, exit 137 token is present in transport stderr, and
    app_has_mem_limit=False — without the veto, the dmesg arm would match
    and emit env/env.oom. The OOMKilled=False veto MUST fire before the
    dmesg check and force functional. The docker daemon's OOMKilled bit
    is authoritative both ways."""
    ctx = FailureContext(
        phase_reached="app_build",
        raw_evidence="Killed\nexit 137\n",
        build_stderr="",
        up_stderr="service_app_1 exited with code 137\n",
        dmesg_recent=(
            "[12345.678] oom-kill:constraint=CONSTRAINT_NONE,nodemask=(null),"
            "cpuset=/,mems_allowed=0,global_oom,task_memcg=/system.slice/neighbor.service,"
            "task=neighbor_proc,pid=4242,uid=0\n"
            "[12345.679] Out of memory: Killed process 4242 (neighbor_proc)\n"
        ),
        docker_inspect_state={"OOMKilled": False, "ExitCode": 137, "Status": "exited"},
        app_has_mem_limit=False,
        runner_injected_mem_limit="2g",  # R2 prereq satisfied — D1 veto is what fires
        foreign_holder_found=None,
        injected_port=None,
        retry_count=1,
    )
    v = classify(ctx)
    assert v.verdict == "functional"
    assert v.matched_signature is None


def test_V_round4_oom_OOMKilled_None_falls_through_to_dmesg_is_env():
    """Positive control for D1: when docker_inspect_state is None (inspect
    unavailable), inspect.get('OOMKilled') returns None, so neither the True
    carve-out nor the new False veto fires. Positive matches in transport
    stderr (container-exit channel), CONSTRAINT_MEMCG absent,
    app_has_mem_limit=False, runner_injected_mem_limit set, dmesg
    CONSTRAINT_NONE present → env.oom emits. Proves the veto does NOT
    over-fire on the None case and the dmesg fallthrough still works."""
    ctx = FailureContext(
        phase_reached="app_build",
        raw_evidence="",
        build_stderr="",
        up_stderr="service_app_1 exited with code 137\nKilled\n",
        dmesg_recent=(
            "[12345.678] oom-kill:constraint=CONSTRAINT_NONE,nodemask=(null),"
            "cpuset=/,mems_allowed=0,global_oom,task=app_proc,pid=9999,uid=0\n"
            "[12345.679] Out of memory: Killed process 9999 (app_proc)\n"
        ),
        docker_inspect_state=None,  # no inspect data → OOMKilled absent → veto MUST NOT fire
        app_has_mem_limit=False,
        runner_injected_mem_limit="2g",
        foreign_holder_found=None,
        injected_port=None,
        retry_count=1,
    )
    v = classify(ctx)
    assert v.verdict == "env"
    assert v.matched_signature == "env.oom"


# --- D2: channel-provenance restriction (raw_evidence excluded) ------------


def test_V_round4_oom_app_log_137_killed_is_functional():
    """★ R1 round-13 D2 launder trap: the only '137 Killed' tokens live in
    raw_evidence (= compose logs = app output) and the docker daemon
    authoritatively reports ExitCode=0; the downstream noisy-neighbor dmesg
    CONSTRAINT_NONE never gets to fire. Pure app text can NEVER on its own
    promote a run to env.oom."""
    ctx = FailureContext(
        phase_reached="app_runtime",
        raw_evidence=(
            "[app] background worker reported: child process 137 Killed (retrying)\n"
            "[app] continuing...\n"
        ),
        build_stderr="",
        up_stderr="",  # docker CLI is silent — container did not exit through transport
        docker_inspect_state={"OOMKilled": None, "ExitCode": 0},  # container is fine
        app_has_mem_limit=False,
        runner_injected_mem_limit="2g",
        dmesg_recent=(
            "oom-kill:constraint=CONSTRAINT_NONE,nodemask=(null),...\n"
            "Out of memory: Killed process 4242 (neighbor-svc) total-vm:...\n"
        ),
        retry_count=0,
    )
    v = classify(ctx)
    assert v.verdict == "functional"
    assert v.matched_signature is None


def test_V_round4_oom_real_container_exit_137_OOMKilled_unknown_is_env():
    """Positive control for D2: both container-exit channels (transport stderr
    'exited with code 137' AND docker_inspect_state.ExitCode==137) confirm
    the container truly died with 137; OOMKilled is None (unknown, not False,
    so the D1 veto does NOT trip); no own-cgroup carve-out applies
    (OOMKilled!=True, app_has_mem_limit=False, no CONSTRAINT_MEMCG); host
    CONSTRAINT_NONE corroborates. Proves the channel close did NOT
    under-include legitimate env.oom."""
    ctx = FailureContext(
        phase_reached="app_runtime",
        raw_evidence="",
        build_stderr="",
        up_stderr=(
            "Error response from daemon: container abc123def456 exited with code 137\n"
        ),
        docker_inspect_state={"ExitCode": 137, "OOMKilled": None},  # daemon couldn't tell
        app_has_mem_limit=False,
        runner_injected_mem_limit="2g",
        dmesg_recent=(
            "oom-kill:constraint=CONSTRAINT_NONE,nodemask=(null),...\n"
            "Out of memory: Killed process 7777 (target-container) total-vm:...\n"
        ),
        retry_count=0,
    )
    v = classify(ctx)
    assert v.verdict == "env"
    assert v.matched_signature == "env.oom"


# --- D3: by-construction symmetric mem_limit injection precondition --------


def test_V_round4_oom_no_injected_mem_limit_is_functional():
    """★ R2 round-13 D3 launder trap: without runner_injected_mem_limit,
    env.oom is structurally undecidable — the host-level CONSTRAINT_NONE OOM
    could equally well be an unconstrained-app self-leak that incidentally
    exhausted host memory. The new prerequisite in _check_oom() short-circuits
    to None (→ FUNCTIONAL via terminal default). This is the conservative,
    by-construction call."""
    ctx = FailureContext(
        run_id="v-round4-no-inject",
        spec_id="simple_blog",
        arm="spike",
        phase_reached="app_runtime",
        outcome="fail",
        raw_evidence="backend_1 exited with code 137 (Killed)\n",
        build_stderr="",
        up_stderr="ERROR: for backend  Container exited with non-zero status: 137",
        dmesg_recent=(
            "[Tue May 30 10:14:02 2026] Out of memory: Killed process 91234 (node) "
            "total-vm:2148000kB ...\n"
            "[Tue May 30 10:14:02 2026] oom-kill:"
            "constraint=CONSTRAINT_NONE,nodemask=(null),cpuset=/,mems_allowed=0,"
            "global_oom,task_memcg=/system.slice/docker.service,task=node,pid=91234,"
            "uid=0\n"
        ),
        docker_inspect_state={"Status": "exited", "ExitCode": 137, "OOMKilled": None},
        docker_ps_filter_output="",
        compose_project_name="northstar-noinj",
        daemon_up_at_failure_time=True,
        journal_dockerd_window=None,
        injected_port=43210,
        retry_count=0,
        second_collision_on_free_port=False,
        foreign_holder_found=None,
        reassign_retry_success=None,
        app_has_mem_limit=False,
        runner_injected_mem_limit=None,   # <-- the discriminator
    )
    v = classify(ctx)
    assert v.verdict == "functional"
    assert v.matched_signature is None


def test_V_round4_oom_with_injected_mem_limit_and_OOMKilled_None_is_env():
    """Positive control for D3: runner_injected_mem_limit='2g' guarantees that
    an app self-leak above 2 GiB would have hit the injected cgroup ceiling
    and surfaced as CONSTRAINT_MEMCG / OOMKilled=True, triggering the step-1
    own-cgroup carve-out. Since OOMKilled is None (not False — daemon didn't
    affirmatively veto) and not True (didn't hit own ceiling) and dmesg shows
    host-level CONSTRAINT_NONE, the only structurally remaining cause is
    co-tenant pressure that happened to kill this container — env.oom."""
    ctx = FailureContext(
        run_id="v-round4-inject-2g",
        spec_id="simple_blog",
        arm="spike",
        phase_reached="app_runtime",
        outcome="fail",
        raw_evidence="backend_1 exited with code 137 (Killed)\n",
        build_stderr="",
        up_stderr="ERROR: for backend  Container exited with non-zero status: 137",
        dmesg_recent=(
            "[Tue May 30 10:18:55 2026] Out of memory: Killed process 99001 (node) "
            "total-vm:1640000kB ...\n"
            "[Tue May 30 10:18:55 2026] oom-kill:"
            "constraint=CONSTRAINT_NONE,nodemask=(null),cpuset=/,mems_allowed=0,"
            "global_oom,task_memcg=/system.slice/docker.service,task=node,pid=99001,"
            "uid=0\n"
        ),
        docker_inspect_state={"Status": "exited", "ExitCode": 137, "OOMKilled": None},
        docker_ps_filter_output="",
        compose_project_name="northstar-inj2g",
        daemon_up_at_failure_time=True,
        journal_dockerd_window=None,
        injected_port=43211,
        retry_count=0,
        second_collision_on_free_port=False,
        foreign_holder_found=None,
        reassign_retry_success=None,
        app_has_mem_limit=False,                # compose did not declare mem_limit itself
        runner_injected_mem_limit="2g",          # <-- runner injected; app self-leak would have own-cgroup'd first
    )
    v = classify(ctx)
    assert v.verdict == "env"
    assert v.matched_signature == "env.oom"
