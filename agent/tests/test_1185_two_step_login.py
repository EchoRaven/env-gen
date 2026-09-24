"""#1185 — the login page takes two submits, and nothing said so.

#540 gives this design its real login: a single-step flow (email, then password), which is
what the reference screenshots show. In the generated page that becomes

    const single = true;
    if (single && step === 0 && !isRegister) { setStep(1); return; }
    ... (single && step === 1 ? 'Sign In' : 'Continue')

so the FIRST submit issues no request — it reveals the password field and relabels the
button. A walk that fills the email, clicks once and considers itself logged in is anonymous,
and the next protected page 401s. r21's terminal record was exactly that:

    validation:ui_flow:login_profile_catalog_my_list_flow  FAILED
      "after login submit, /profiles triggers GET /api/profiles 401 Unauthorized"

Driven in a real browser against that same stack: email -> "Continue" (no request, password
appears) -> password -> "Sign In" -> /auth/login 200 -> /api/profiles 200 -> /profiles, token
stored. The flow works; one submit is half of it. Present in 7 of 7 netflix runs measured.
"""
import json

from env_generator.llm_generator.multi_agent.runtime.remediation_dispatcher import (
    two_step_login_1185, _single_step_login_1185,
)


class _Orch:
    def __init__(self, root):
        self.output_dir = str(root)


_SINGLE_STEP = (
    "export default function LoginPage() {\n"
    "  const [step, setStep] = useState(0);\n"
    "  const single = true;\n"
    "  const onSubmit = async (e) => {\n"
    "    if (single && step === 0 && !isRegister) { setStep(1); return; }\n"
    "  };\n"
    "  return <button type='submit'>{isRegister ? 'Create account' : "
    "(single && step === 1 ? 'Sign In' : 'Continue')}</button>;\n}\n"
)
_PLAIN = ("export default function LoginPage() {\n"
          "  return <button type='submit'>Log in</button>;\n}\n")


def _project(tmp_path, summary, login_src=_SINGLE_STEP):
    hubs = tmp_path / "shared" / "hubs"
    hubs.mkdir(parents=True)
    (hubs / "codehub_checks.json").write_text(json.dumps({"checks": [{
        "name": "validation:ui_flow:login_profile_catalog_my_list_flow",
        "status": "failure", "evidence": {"summary": summary}}]}))
    pages = tmp_path / "app" / "frontend" / "src" / "pages"
    pages.mkdir(parents=True)
    (pages / "LoginPage.jsx").write_text(login_src)
    return _Orch(tmp_path)


def test_the_second_submit_is_named(tmp_path):
    orch = _project(tmp_path, "Live re-walk failed: after login submit, /profiles triggers "
                              "GET /api/profiles 401 Unauthorized")
    out = two_step_login_1185(orch, ["login_profile_catalog_my_list_flow"])
    assert out, "r21's terminal record must be answered"
    assert "TWO SUBMITS" in out and "LoginPage.jsx" in out
    assert "`Continue`" in out and "`Sign In`" in out, "both labels must be given"
    assert "sends NO request" in out or "SENDS NO request" in out.upper()
    # It must not close the item.
    assert "that is a real defect" in out and "bug_create" in out


def test_a_plain_login_page_says_nothing(tmp_path):
    """No step gate -> the advice would be wrong, so there must be none."""
    orch = _project(tmp_path, "after login submit /api/profiles 401", login_src=_PLAIN)
    assert two_step_login_1185(orch, ["login_profile_catalog_my_list_flow"]) == ""


def test_a_failure_unrelated_to_auth_says_nothing(tmp_path):
    orch = _project(tmp_path, "the catalog grid rendered zero rows")
    assert two_step_login_1185(orch, ["login_profile_catalog_my_list_flow"]) == ""


def test_only_the_flows_the_gate_named(tmp_path):
    orch = _project(tmp_path, "after login submit /api/profiles 401")
    assert two_step_login_1185(orch, ["some_other_flow"]) == ""


def test_the_gate_is_the_setstep_line_not_the_word_step(tmp_path):
    """A page that merely mentions `step` must not be reported as two-submit."""
    decoy = ("export default function LoginPage(){ const step = 'one step'; "
             "return <div>{step}</div>; }")
    orch = _project(tmp_path, "after login submit /api/profiles 401", login_src=decoy)
    assert _single_step_login_1185(orch.output_dir) == (None, ())
    assert two_step_login_1185(orch, ["login_profile_catalog_my_list_flow"]) == ""


def test_labels_are_read_from_the_page_not_assumed(tmp_path):
    renamed = _SINGLE_STEP.replace("'Sign In' : 'Continue'", "'Enter' : 'Next'")
    orch = _project(tmp_path, "after login submit /api/profiles 401", login_src=renamed)
    out = two_step_login_1185(orch, ["login_profile_catalog_my_list_flow"])
    assert "`Next`" in out and "`Enter`" in out
