r"""#1202zi: `scripts/verify_shipped_fixes.py` must never report a silence as a pass.

The script exists because six behaviour changes and two instruments shipped on 2026-09-29
with NO live verification — the provider account hit zero credits and r141 died at 82.7 s on
`429 insufficient_quota`. The checkpoints lived only as prose in a memory file, so the first
thing that happens when credits return is re-deriving which file to open. That is friction at
exactly the bottleneck.

★ THE PROPERTY THAT MATTERS IS THE THIRD VERDICT. A checker with only pass/fail turns "the
artifact is absent" into one of them, and an absent artifact is not evidence either way. This
is #1202z5 one directory over: `count: 0` from an audit that inspected nothing must not read
as clean. So every check answers CONFIRMED / FALSIFIED / NOT MEASURED, and the tests below
pin that an empty run directory produces NOT MEASURED everywhere and CONFIRMED nowhere.

The fixtures are synthetic on purpose: the script's own `--self-test` runs against
`generated/tiktok-web-r140`, which is not in git, so a test that depended on it would pass or
fail by accident of the machine.
"""
import importlib.util
import json
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT = os.path.join(os.path.dirname(_AGENT), "scripts", "verify_shipped_fixes.py")


def _mod():
    spec = importlib.util.spec_from_file_location("verify_shipped_fixes_1202zi", _SCRIPT)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m


def _verdicts(capsys):
    """The verdict word from each printed line, stripped of colour."""
    out = capsys.readouterr().out
    words = []
    for line in out.splitlines():
        plain = line.replace("\033[32m", "").replace("\033[31m", "") \
                    .replace("\033[33m", "").replace("\033[0m", "")
        for v in ("NOT MEASURED", "CONFIRMED", "FALSIFIED"):
            if plain.startswith("#") or plain.startswith("cost"):
                if v in plain:
                    words.append(v)
                    break
    return words


def _run_all(m, run):
    for c in m.CHECKS:
        c(run)


def test_the_script_is_where_the_memory_says_it_is():
    assert os.path.isfile(_SCRIPT), _SCRIPT


def test_an_empty_run_is_never_reported_as_a_pass(tmp_path, capsys):
    """★ The whole point. Nothing on disk means nothing is known."""
    (tmp_path / "logs").mkdir()
    m = _mod()
    _run_all(m, tmp_path)
    v = _verdicts(capsys)
    assert v, "no verdicts printed"
    assert m.CONFIRMED not in v, "an empty run produced a CONFIRMED: %r" % v
    assert v.count(m.UNMEASURED) >= 5, v


def test_a_converged_tool_menu_confirms(tmp_path, capsys):
    (tmp_path / "run_budget.json").write_text(json.dumps({"stage_tool_sets_1202zc": {
        "orchestrator:action": {"calls": 300, "distinct_sets": 2,
                                "union_size": 24, "capped": False}}}), encoding="utf-8")
    m = _mod()
    m.check_1202zc(tmp_path)
    assert m.CONFIRMED in _verdicts(capsys)[0]


def test_a_still_rotating_menu_is_falsified(tmp_path, capsys):
    (tmp_path / "run_budget.json").write_text(json.dumps({"stage_tool_sets_1202zc": {
        "orchestrator:action": {"calls": 300, "distinct_sets": 240,
                                "union_size": 30, "capped": False}}}), encoding="utf-8")
    m = _mod()
    m.check_1202zc(tmp_path)
    assert m.FALSIFIED in _verdicts(capsys)[0]


def test_the_cap_binding_is_falsified_not_celebrated(tmp_path, capsys):
    """★ `capped: true` means the union outgrew 32, i.e. the number chosen from a measured
    max of 25 was wrong. A converged-looking `distinct_sets` must not hide that."""
    (tmp_path / "run_budget.json").write_text(json.dumps({"stage_tool_sets_1202zc": {
        "orchestrator:action": {"calls": 300, "distinct_sets": 1,
                                "union_size": 32, "capped": True}}}), encoding="utf-8")
    m = _mod()
    m.check_1202zc(tmp_path)
    assert m.FALSIFIED in _verdicts(capsys)[0]


def _store(tmp_path, body):
    d = tmp_path / "app" / "backend"
    d.mkdir(parents=True, exist_ok=True)
    (d / "oauth_store.py").write_text(body, encoding="utf-8")


def test_the_old_fixed_returning_is_falsified(tmp_path, capsys):
    _store(tmp_path, 'x = "INSERT INTO users RETURNING id, email, name, tenant_id"\n')
    m = _mod()
    m.check_1202zd(tmp_path)
    assert m.FALSIFIED in _verdicts(capsys)[0]


def test_a_derived_returning_without_the_coercion_is_falsified(tmp_path, capsys):
    """★ The regression this ticket nearly shipped: widening RETURNING without the row
    coercion 500s every register on any app with a `created_at`."""
    _store(tmp_path, '_ret = [c for c in existing]\n')
    m = _mod()
    m.check_1202zd(tmp_path)
    assert m.FALSIFIED in _verdicts(capsys)[0]


def test_a_derived_returning_with_the_coercion_confirms(tmp_path, capsys):
    _store(tmp_path, '_ret = [c for c in existing]\n'
                     'def _json_safe_row_1202zd(row): return row\n')
    m = _mod()
    m.check_1202zd(tmp_path)
    assert m.CONFIRMED in _verdicts(capsys)[0]


def test_media_still_missing_is_falsified(tmp_path, capsys):
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "logs" / "unstaged_seed_media_1202xn.jsonl").write_text(
        json.dumps({"rows": ["/assets/real_videos/a.mp4 (not staged)"]}) + "\n",
        encoding="utf-8")
    m = _mod()
    m.check_1202zf(tmp_path)
    assert m.FALSIFIED in _verdicts(capsys)[0]


def test_media_reported_then_staged_confirms(tmp_path, capsys):
    """★ r139: 1,260 scaffold-time entries and a CLEAN delivered tree, because the framework
    rewrote `.dockerignore` ten seconds after the last report. A verifier that called that a
    failure would cry wolf on every run."""
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "logs" / "unstaged_seed_media_1202xn.jsonl").write_text(
        json.dumps({"rows": ["/assets/real_videos/a.mp4 (not staged)"]}) + "\n",
        encoding="utf-8")
    d = tmp_path / "app" / "frontend" / "public" / "assets" / "real_videos"
    d.mkdir(parents=True, exist_ok=True)
    (d / "a.mp4").write_text("x", encoding="utf-8")
    m = _mod()
    m.check_1202zf(tmp_path)
    assert m.CONFIRMED in _verdicts(capsys)[0]


def test_a_blind_reporter_record_is_not_a_finding(tmp_path, capsys):
    """`measured: false` on every record means the check could not look."""
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "logs" / "unreachable_twin_table_1202zb.jsonl").write_text(
        json.dumps({"measured": False, "why": "no live row counts", "count": 0}) + "\n",
        encoding="utf-8")
    m = _mod()
    m.check_1202zb(tmp_path)
    assert m.UNMEASURED in _verdicts(capsys)[0]


def test_a_broken_check_does_not_hide_the_others(tmp_path, capsys):
    """One check raising must not cost the report its other answers."""
    m = _mod()

    def _boom(run):
        raise RuntimeError("lost the plot")
    m.CHECKS = [_boom] + list(m.CHECKS)
    rc = m.main(["verify", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "the check itself raised" in out
    assert "#1202zd" in out, "the later checks did not run"


def test_every_check_answers_not_measured_on_an_empty_run(tmp_path, capsys):
    """★ Every check, one at a time, not just the report as a whole.

    The first version of this read each check's SOURCE for the word `UNMEASURED` and failed
    on correct code: `check_1202zb` and `check_1202ze` delegate to `_reporter`, where the
    branch lives. A textual test cannot see through a delegation — asking the function what
    it ANSWERS can.
    """
    (tmp_path / "logs").mkdir(exist_ok=True)
    m = _mod()
    for c in m.CHECKS:
        c(tmp_path)
        got = _verdicts(capsys)
        assert got and got[0] == m.UNMEASURED, \
            "%s answered %r on an empty run" % (c.__name__, got)
