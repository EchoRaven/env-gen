"""#1202wu: the password probe's account must not land among the app's own users.

#1202vb creates an account because that is what makes it domain-agnostic: it needs no
seeded user and no knowledge of the app's cast. The account then shipped. #1202w7 measured
the delivered r132 and r135 at 12 users -- 9 seeded, 3 added by the run -- and this probe is
one of the three; a person opening either app finds `pwcheck_1202vb_...@example.com` among
its people.

`/auth/register` and `/auth/login` both accept `tenant_id` in the body, and the body wins
over the X-Tenant-Id header, so the whole exchange can happen in a tenant the app never
reads. The verification path is unchanged -- `verify_user_password(email, password,
tenant_id=...)` -- so the probe still answers the same question: does login check the
password at all.

Every request in the exchange must carry the tenant. A register in one tenant and a login
in another would fail for the wrong reason and read as "the app rejects a correct password".
"""
import ast
import os
import sys

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

_RUNNER = os.path.join(_AGENT, "env_generator", "llm_generator", "multi_agent", "runtime",
                       "validation_runner.py")


def _read(path):
    with open(path, encoding="utf-8") as fh:      # #1202eu
        return fh.read()


def _probe_calls():
    """Every `_http` call in the probe block, as {url_suffix: body keys}."""
    tree = ast.parse(_read(_RUNNER))
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id.startswith("_pw_")):
            continue
        call = node.value
        if not (isinstance(call, ast.Call) and getattr(call.func, "id", "") == "_http"):
            continue
        body = next((k.value for k in call.keywords if k.arg == "body"), None)
        keys = set()
        if isinstance(body, ast.Dict):
            keys = {k.value for k in body.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        out.append((node.targets[0].id, ast.unparse(call.args[1]), keys))
    return out


def test_the_probe_block_is_found():
    calls = _probe_calls()
    assert len(calls) >= 4, (
        "expected the register plus three logins #1202vb makes: %r" % [c[0] for c in calls])


def test_every_request_in_the_exchange_carries_a_tenant():
    missing = [name for name, _url, keys in _probe_calls() if "tenant_id" not in keys]
    assert not missing, (
        "these would run in the app's own tenant, so the probe account ships with the app: "
        "%r" % missing)


def test_register_and_login_agree_on_the_tenant():
    """A mismatch fails for the wrong reason and reads as 'a correct password was rejected'."""
    src = _read(_RUNNER)
    tree = ast.parse(src)
    literals = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id.startswith("_pw_")):
            continue
        call = node.value
        if not (isinstance(call, ast.Call) and getattr(call.func, "id", "") == "_http"):
            continue
        body = next((k.value for k in call.keywords if k.arg == "body"), None)
        if not isinstance(body, ast.Dict):
            continue
        for k, v in zip(body.keys, body.values):
            if isinstance(k, ast.Constant) and k.value == "tenant_id":
                literals.add(ast.unparse(v))
    assert len(literals) == 1, (
        "the exchange spans more than one tenant: %r" % sorted(literals))


def test_the_tenant_is_not_the_default_one():
    src = _read(_RUNNER)
    assert '"fw_pwcheck_1202vb"' in src or "'fw_pwcheck_1202vb'" in src, (
        "the probe tenant must be a name the app never reads")
    assert '"tenant_id": "default"' not in src


def test_the_verdict_still_reads_all_four_statuses():
    """★ Isolation must not quietly narrow what the probe checks."""
    src = _read(_RUNNER)
    call = next((n for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "wrong_password_verdict_1202vb"), None)
    assert call is not None, "the verdict call is gone"
    assert len(call.args) == 4, (
        "the verdict is derived from register/ok/wrong/ghost; got %d args" % len(call.args))
