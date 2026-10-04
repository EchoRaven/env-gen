r"""#1203d7: the smoke said why REGISTER failed, when what failed was the LOGIN.

`api_smoke`'s auth check registers a fixed smoke user, and if that mints no token it logs in:

    login = _http("POST", f"{base}/auth/login", body={...})
    token = _tok(login["body_text"])
    _add("auth_register_login", bool(token),
         "" if token else f"register={reg['status']} + login; no access_token "
                          f"({reg['body_text'][:200]})")

`login["status"]` and `login["body_text"]` are computed on the line above and then discarded.
The evidence kept for the failure is the REGISTER response.

MEASURED over every run directory: 99 records of this failure across 49 runs. In **30 of them
(30%)** the register body only says the user already exists -- `could not register: duplicate
key value violates unique constraint` -- which is the EXPECTED answer when a previous milestone
already registered the smoke user. So the sole surviving evidence for a delivery-blocking
failure was a harmless message, and why login refused was written down nowhere.

r149 is the live case: its 1.1.0 was held by `auth_register_login`, and searching its entire run
directory for the full text finds only the one truncated ledger line. The reason is gone.

The register body is NOT dropped, because in the other 69 records it IS the cause: 55 `relation
"tenants" does not exist`, 5 `'OAuthStore' object has no attribute 'db'`, 4 a rejected request
body, 4 an unreachable database. Both are reported, login first.
"""
import ast
import inspect
import os
import re
import sys
import textwrap

_AGENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_AGENT, "env_generator", "llm_generator"))

from multi_agent.runtime import validation_runner as VR  # noqa: E402


def _stanza():
    """Bounded by two landmarks, never a byte count (#943)."""
    src = inspect.getsource(VR)
    i = src.index('reg = _http("POST", f"{base}/auth/register"')
    j = src.index('_add("auth_register_login"', i)
    j = src.index("\n", j)
    return src[i:j]


def _detail(reg_status, reg_body, login_status, login_body):
    """Rebuild the recorded detail by EXECUTING the shipped expression, not a replica of it --
    the mistake #1203d4 had to undo in #1008's own test file.

    The block is taken as a CONTIGUOUS line range between two landmarks and dedented, because
    the assignment spans two lines and a line-by-line filter silently drops the continuation.
    (It did, in the first draft of this helper.)"""
    lines = _stanza().split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.strip().startswith("_d7 = "))
    end = next(i for i, ln in enumerate(lines)
               if '_add("auth_register_login"' in ln)
    block = textwrap.dedent("\n".join(lines[start:end]))
    ns = {"login": {"status": login_status, "body_text": login_body},
          "reg": {"status": reg_status, "body_text": reg_body}}
    exec(compile(block, "<stanza>", "exec"), ns)
    return ns["_d7"]


def test_the_login_status_and_body_are_reported():
    """★ The defect: the thing that failed must be the thing described."""
    d = _detail(409, '{"detail":"could not register: duplicate key value violates unique '
                     'constraint \\"users_email_key\\""}',
                401, '{"detail":"incorrect username or password"}')
    assert "login=401" in d, d
    assert "incorrect username or password" in d, d


def test_the_register_body_is_still_reported():
    """The 69 of 99 records where the register body IS the cause must not lose it."""
    d = _detail(500, '{"detail":"could not register: relation \\"tenants\\" does not exist"}',
                401, '{"detail":"no such user"}')
    assert 'relation \\"tenants\\" does not exist' in d, d
    assert "register=500" in d, d


def test_the_login_comes_first():
    """#1034: the operative half must survive a truncating reader. r149's line was cut at 60."""
    d = _detail(409, "x" * 300, 401, '{"detail":"tenant header required"}')
    assert d.index("login=") < d.index("register="), d
    assert "tenant header required" in d[:160], d[:200]


def test_r149s_shape_now_names_the_login():
    """r149's register half, verbatim, with a plausible login refusal beside it."""
    d = _detail(409, '{"detail":"could not register: duplicate key value violates unique '
                     'constraint"}', 400, '{"detail":"tenant_id is required"}')
    assert d.startswith("login=400"), d
    assert "tenant_id is required" in d, d
    assert "duplicate key" in d, "the register context was dropped: " + d


def test_the_pair_fits_the_ledger_budget():
    """#1203d5 gave this line 300 characters of the 400-char ledger field; two 140-char halves
    plus the labels must stay inside it."""
    d = _detail(409, "r" * 500, 401, "l" * 500)
    assert len(d) <= 300, len(d)


def test_neither_half_is_dropped_when_a_body_is_empty():
    d = _detail(409, "", 401, "")
    assert "login=401" in d and "register=409" in d, d


def test_a_missing_login_response_does_not_raise():
    """`login` is None until the register path falls through; the expression must tolerate it
    rather than be the reason a smoke run dies."""
    s = _stanza()
    assert "(login or {})" in s, "an un-guarded `login[...]` can raise here:\n" + s


# ---------------------------------------------------------------- wiring

def test_login_is_bound_before_the_branch():
    """★ The subtle half: `login` used to exist only inside `if not token:`. Pin that it is
    initialised at function scope, so the detail expression can always read it."""
    s = _stanza()
    assert re.search(r"^\s*login = None\s*$", s, re.M), s


def test_the_check_still_reports_a_clean_pass_as_empty():
    """A passing auth check must stay detail-free; #1202wc's ledger reads an empty detail as
    'nothing to say', and a success that explains itself is noise."""
    s = _stanza() + inspect.getsource(VR)[
        inspect.getsource(VR).index('_add("auth_register_login"'):][:200]
    assert '"" if token else' in s, s[-300:]


def test_the_discarded_values_are_gone_from_the_source():
    """Counter-proof pinned structurally: no reading of `reg["body_text"]` as the ONLY evidence
    survives in this stanza."""
    s = _stanza()
    assert "no access_token" not in s, "the old message is still being built:\n" + s


def test_the_detail_block_is_self_contained():
    """The helper above exec()s a contiguous block out of the shipped source. Pin that the block
    depends on nothing but `login` and `reg`, so this file cannot quietly end up testing a
    replica if the shape moves (#1202lq: a green test can prove nothing)."""
    lines = _stanza().split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.strip().startswith("_d7 = "))
    end = next(i for i, ln in enumerate(lines) if '_add("auth_register_login"' in ln)
    block = textwrap.dedent("\n".join(lines[start:end]))
    names = {n.id for n in ast.walk(ast.parse(block)) if isinstance(n, ast.Name)}
    assert names <= {"_d7", "login", "reg", "str"}, sorted(names)
