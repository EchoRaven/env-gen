"""#1203g7 — three callers each inspected all 16 candidate containers for the same label.

`compute_deliverability` takes 5.47s on tiktok-r164's tree and 2.87s of that — 52% — is 112
subprocesses, dominated by `docker inspect <id>`. This machine has 16 containers named
`database`, and EACH WAS INSPECTED THREE TIMES in one pass: three callers resolve the container
independently and each loops over every candidate id, reading the same
`com.docker.compose.project.config_files` label every time. `deliverability_check` is the second
most expensive tool in the corpus — 931s over 443 calls at 2101ms each — so this is paid 443
times over.

A container's labels are fixed at CREATE time (`docker update` cannot change them) and an id is
unique and never reused, so caching the label BY ID is exact rather than a heuristic.
`State.Status` is deliberately NOT cached: it changes, and a stale "running" is precisely the
confident wrong answer #962 exists to prevent.

Measured after: the first pass makes 24 subprocesses instead of 112 (16 inspects, not 48) and
every later pass in the same process makes ZERO inspects — 2.87s -> 1.29s -> 0.41s.
"""
import sys
from pathlib import Path

import pytest

_AGENT = Path(__file__).resolve().parents[1]
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from env_generator.llm_generator.multi_agent.runtime import container_runtime as CR  # noqa: E402


class _Result:
    def __init__(self, stdout=""):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = 0


@pytest.fixture(autouse=True)
def _clear():
    CR._CONFIG_FILES_LABEL_1203G7.clear()
    yield
    CR._CONFIG_FILES_LABEL_1203G7.clear()


@pytest.fixture
def spy(monkeypatch):
    """Record every subprocess the module makes, and answer like docker would."""
    seen = []

    def fake(cmd, *a, **k):
        seen.append(list(cmd))
        if len(cmd) > 1 and cmd[1] == "inspect":
            fmt = cmd[-1]
            if "config_files" in fmt:
                return _Result("/wanted/docker-compose.yml\n")
            return _Result("exited|1\n")
        return _Result("")

    monkeypatch.setattr(CR.subprocess, "run", fake)
    return seen


def test_the_label_is_asked_once_per_container(spy):
    for _ in range(5):
        assert CR._config_files_label_1203g7("docker", "abc123", 5) == \
            "/wanted/docker-compose.yml"
    inspects = [c for c in spy if len(c) > 1 and c[1] == "inspect"]
    assert len(inspects) == 1, "%d inspects for one container id" % len(inspects)


def test_two_ids_are_asked_separately(spy):
    CR._config_files_label_1203g7("docker", "aaa", 5)
    CR._config_files_label_1203g7("docker", "bbb", 5)
    CR._config_files_label_1203g7("docker", "aaa", 5)
    inspects = [c for c in spy if len(c) > 1 and c[1] == "inspect"]
    assert len(inspects) == 2, [c[2] for c in inspects]


def test_a_different_runtime_is_a_different_key(spy):
    CR._config_files_label_1203g7("docker", "aaa", 5)
    CR._config_files_label_1203g7("podman", "aaa", 5)
    inspects = [c for c in spy if len(c) > 1 and c[1] == "inspect"]
    assert len(inspects) == 2


def test_an_empty_label_is_cached_too(spy):
    """A container with no compose label will never grow one, so "" is an ANSWER. Caching it is
    what keeps a stray container from being re-inspected on every pass."""
    def fake(cmd, *a, **k):
        spy.append(list(cmd))
        return _Result("\n")
    CR.subprocess.run = fake
    assert CR._config_files_label_1203g7("docker", "stray", 5) == ""
    assert CR._config_files_label_1203g7("docker", "stray", 5) == ""
    assert len([c for c in spy if len(c) > 1 and c[1] == "inspect"]) == 1


def test_a_failed_ask_is_not_cached(monkeypatch):
    """None means "could not ask", which is recoverable — caching it would make one transient
    docker hiccup permanent for the process."""
    calls = []

    def boom(cmd, *a, **k):
        calls.append(1)
        raise OSError("docker gone")

    monkeypatch.setattr(CR.subprocess, "run", boom)
    assert CR._config_files_label_1203g7("docker", "x", 5) is None
    assert CR._config_files_label_1203g7("docker", "x", 5) is None
    assert len(calls) == 2
    assert ("docker", "x") not in CR._CONFIG_FILES_LABEL_1203G7


def test_the_cache_is_bounded(spy):
    cap = CR._LABEL_CACHE_MAX_1203G7
    for i in range(cap + 3):
        CR._config_files_label_1203g7("docker", "id%d" % i, 5)
    assert len(CR._CONFIG_FILES_LABEL_1203G7) <= cap


# ------------------------------------------------------- the status must stay live

def test_the_status_is_never_cached():
    """★ The one thing that must NOT be cached. A container's labels are immutable; its status
    is not, and a stale "running" is the confident wrong answer #962 exists to prevent."""
    import inspect
    src = inspect.getsource(CR._config_files_label_1203g7)
    for forbidden in ("State.Status", "State.ExitCode", ".Status}}"):
        assert forbidden not in src, forbidden


def test_the_exit_reason_asks_the_status_live():
    """`_exited_container_reason_1202av` reads the label from the cache and the status from
    docker, in that order — so a non-matching container costs no status call at all."""
    import inspect
    src = inspect.getsource(CR._exited_container_reason_1202av)
    i = src.index("_config_files_label_1203g7")
    j = src.index("State.Status")
    assert i < j, "the label gate must come before the status inspect"
    import ast
    tree = ast.parse(src.lstrip())
    fmts = [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    combined = [f for f in fmts
                if "{{index .Config.Labels" in f and "State.Status" in f]
    assert combined == [], (
        "the status inspect still re-reads the label in one format: %s" % combined)


def test_container_id_uses_the_cache_not_its_own_inspect():
    """Over the AST's STRING CONSTANTS, not the raw source: the function's own comment explains
    the config_files label, and a text search counts that explanation as code. (Same trap as
    #1203g2's first assertion, one ticket earlier.)"""
    import ast
    import inspect
    src = inspect.getsource(CR.container_id)
    tree = ast.parse(src.lstrip())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "_config_files_label_1203g7" in names, sorted(names)
    # Narrowed twice: "config_files" appears in this function's COMMENT and in three of its
    # log messages, both of which are legitimate. What must be gone is a docker --format
    # TEMPLATE that reads the label, i.e. a string carrying `{{index .Config.Labels`.
    fmts = [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and "{{index .Config.Labels" in n.value]
    assert fmts == [], "container_id still builds its own label inspect: %s" % fmts


def test_a_stray_container_is_rejected_without_a_status_call(spy, tmp_path):
    """The end-to-end shape of the saving: 16 containers that are not ours cost 16 label reads
    (cached after the first pass) and ZERO status inspects."""
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n", encoding="utf-8")

    def fake(cmd, *a, **k):
        spy.append(list(cmd))
        if len(cmd) > 1 and cmd[1] == "ps":
            return _Result("c1\nc2\nc3\n")
        if len(cmd) > 1 and cmd[1] == "inspect":
            return _Result("/someone/else/docker-compose.yml\n")
        return _Result("")

    CR.subprocess.run = fake
    out = CR._exited_container_reason_1202av("docker", "database", str(compose), 5)
    assert out == ""
    statuses = [c for c in spy if len(c) > 1 and c[1] == "inspect"
                and any("State.Status" in str(x) for x in c)]
    assert statuses == [], "a non-matching container must cost no status inspect"
