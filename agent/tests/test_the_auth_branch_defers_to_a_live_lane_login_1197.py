r"""#1197: the auth branch was the last unconditional clobber — and now it isn't.

`_env_flag_914()` (OFF in #914, ON since #1020) protects every page
`scaffold_pages_from_contract` writes except one: the auth branch
(`_is_auth_page(comp, page) or not target.exists()`) never consulted it. #910b said so in
its own comment — *"this branch is UNCONDITIONAL for an auth page ... and #910's
announcement did not cover it"* — and left which page should win as a user decision.

That decision has been made everywhere else, and the corpus is one-sided. r26:

    AUTH PAGE OVERWRITE      LoginPage 87, SignupPage 58        (145 total)
    what was replaced        18 lines/3 components   44x
                             24 lines/4 components   30x
                             5 lines/1 component     36x
                             26 / 20 / 25 / 17 lines, 3-4 components   35x
                             no components at all     2x

143 of 145 clobbers replaced a component-importing page — the shape `_imports_own_components`
quotes #583 to define as real lane work. Not an r26 accident: r21 76, r25 143, r23 26, r20 16,
every run in the corpus. #939 fires its `SCAFFOLD LOOP` error 141 times in r26 alone.

Deference here is deliberately NARROWER than #914's. This branch exists because "the lane
consistently ships a dead/unwired login", which is a true statement about a dead login, and
importing a component is not evidence that a form logs in. A lane auth page is kept only when
it is wired (reaches the framework-universal `/auth/*` endpoints, or drives an auth context)
AND drivable (a named input + a submit path — what the ui_flow/ui_smoke DOM walk needs, and
what #1179b added `name=` for). Evidence may sit one hop away in an imported component, since
r134's kept page is `<AuthShell><AuthForm/></AuthShell>` and holds neither on its own.

Precedent: #566j already stopped this exact clobber for DETAIL pages, after r117/r120 wedged
deliverability into the 75-minute no-deliver abort by overwriting a real 230-line lane page.
"""

import tempfile
from pathlib import Path

import pytest

from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as fs


_LOGIN_PAGE = {"name": "login", "route": "/login", "component": "LoginPage",
               "path": "app/frontend/src/pages/LoginPage.jsx"}

# r134's shape: the page itself is a delegation and carries no evidence at all.
_LANE_PAGE = (
    "import AuthShell from '../components/AuthShell.jsx';\n"
    "import AuthForm from '../components/AuthForm.jsx';\n"
    "export default function LoginPage(){ return (<AuthShell><AuthForm/></AuthShell>); }\n")

# r26's real shape, which the first draft of this predicate got WRONG in both halves:
#   * the /auth/login literal is TWO hops away (page -> SignInCard -> services/api), and
#   * the named control is a COMPONENT (`<TextInput name="email">`), not a literal <input>.
# A one-hop, <input>-only predicate judged all five real r26 revisions dead.
_WIRED_DRIVABLE = (
    "import { login, register } from '../services/api';\n"
    "import TextInput from './TextInput';\n"
    "export default function AuthForm(){\n"
    "  const submit = async (e) => { e.preventDefault(); await login('a','b'); };\n"
    "  return (<form onSubmit={submit}>\n"
    "    <TextInput name=\"email\" type=\"email\"/>\n"
    "    <TextInput name=\"password\" type=\"password\"/>\n"
    "    <button type=\"submit\">Log in</button></form>); }\n")

_API_MODULE = (
    "export async function login(email, password){\n"
    "  const r = await fetch('/auth/login', {method:'POST'});\n"
    "  const d = await r.json();\n"
    # #1199b: r26's storeSession, in miniature — the projection persists the session and a
    # page that replaces it must too, or every projected page reads no token (#1108).
    "  localStorage.setItem('access_token', d.access_token); return d; }\n"
    "export async function register(email, name, password){\n"
    "  return fetch('/auth/register', {method:'POST'}); }\n")

_TEXT_INPUT = ("export default function TextInput({name, ...props}){\n"
               "  return <input name={name} {...props}/>; }\n")

# Wired, but the DOM walk cannot fill it: no named input.
_WIRED_NOT_DRIVABLE = (
    "import { login } from '../services/api';\n"
    "export default function AuthForm(){\n"
    "  const submit = async () => { await login('a','b'); };\n"
    "  return (<div><input type=\"email\"/><button onClick={submit}>Go</button></div>); }\n")

# A drivable form that logs nobody in — the dead login this branch exists for.
_DEAD = (
    "export default function AuthForm(){\n"
    "  return (<form>\n"
    "    <input name=\"email\" type=\"email\"/>\n"
    "    <button type=\"submit\">Log in</button></form>); }\n")

_SHELL = "export default function AuthShell({children}){ return <div>{children}</div>; }\n"


def _tree(page_src=None, *, form_src=_WIRED_DRIVABLE, shell_src=_SHELL):
    """A frontend tree shaped like a real run's: pages/, components/, services/."""
    fe = Path(tempfile.mkdtemp()) / "app" / "frontend"
    pages = fe / "src" / "pages"
    comps = fe / "src" / "components"
    svcs = fe / "src" / "services"
    pages.mkdir(parents=True)
    comps.mkdir(parents=True)
    svcs.mkdir(parents=True)
    (svcs / "api.js").write_text(_API_MODULE, encoding="utf-8")
    (comps / "TextInput.jsx").write_text(_TEXT_INPUT, encoding="utf-8")
    if shell_src is not None:
        (comps / "AuthShell.jsx").write_text(shell_src, encoding="utf-8")
    if form_src is not None:
        (comps / "AuthForm.jsx").write_text(form_src, encoding="utf-8")
    if page_src is not None:
        (pages / "LoginPage.jsx").write_text(page_src, encoding="utf-8")
    return fe


def _run(fe):
    """Run the real scaffolder over `fe` and return the auth page as it was left."""
    target = fe / "src" / "pages" / "LoginPage.jsx"
    orig = fs._load_design_for_projection
    fs._load_design_for_projection = lambda _fd: None
    try:
        fs.scaffold_pages_from_contract(fe, [_LOGIN_PAGE])
    finally:
        fs._load_design_for_projection = orig
    return target.read_text(encoding="utf-8") if target.exists() else None


def _scaffold(page_src, *, form_src=_WIRED_DRIVABLE, shell_src=_SHELL, write_page=True):
    return _run(_tree(page_src if write_page else None,
                      form_src=form_src, shell_src=shell_src))


def _is_framework_projection(src: str) -> bool:
    """Landmark, not a byte window (#943): the template's own single-source auth path."""
    return "isRegister" in (src or "")


# ------------------------------------------------------------------ the fix, both ways

def test_a_wired_drivable_lane_auth_page_is_kept(monkeypatch):
    """The 143-of-145 case: the page delegates, the component logs in, the lane keeps it."""
    monkeypatch.delenv("ENVGEN_DEFER_TO_LANE_PAGE", raising=False)
    out = _scaffold(_LANE_PAGE)
    assert out == _LANE_PAGE
    assert not _is_framework_projection(out)


def test_the_off_path_still_clobbers_unconditionally(monkeypatch):
    """#914's contract: an explicit 0 restores the previous behaviour exactly."""
    monkeypatch.setenv("ENVGEN_DEFER_TO_LANE_PAGE", "0")
    out = _scaffold(_LANE_PAGE)
    assert out != _LANE_PAGE
    assert _is_framework_projection(out)


# -------------------------------------------------- what deference must NOT extend to

def test_a_dead_login_is_still_replaced(monkeypatch):
    """The branch's own justification, preserved: no auth call anywhere -> project."""
    monkeypatch.delenv("ENVGEN_DEFER_TO_LANE_PAGE", raising=False)
    out = _scaffold(_LANE_PAGE, form_src=_DEAD)
    assert out != _LANE_PAGE
    assert _is_framework_projection(out)


def test_a_login_the_dom_walk_cannot_drive_is_still_replaced(monkeypatch):
    """Wired but unnamed inputs: ui_flow could not fill it, so the projection wins."""
    monkeypatch.delenv("ENVGEN_DEFER_TO_LANE_PAGE", raising=False)
    out = _scaffold(_LANE_PAGE, form_src=_WIRED_NOT_DRIVABLE)
    assert out != _LANE_PAGE
    assert _is_framework_projection(out)


def test_the_frameworks_own_page_is_not_mistaken_for_an_author(monkeypatch):
    """Keeping our own previous projection would freeze it against later improvements."""
    monkeypatch.delenv("ENVGEN_DEFER_TO_LANE_PAGE", raising=False)
    marked = "// framework-projected\n" + _LANE_PAGE
    out = _scaffold(marked)
    assert out != marked
    assert _is_framework_projection(out)


def test_a_missing_auth_page_is_still_projected(monkeypatch):
    """Deference is about not clobbering an author; with no author, project as before."""
    monkeypatch.delenv("ENVGEN_DEFER_TO_LANE_PAGE", raising=False)
    out = _scaffold(_LANE_PAGE, write_page=False)
    assert _is_framework_projection(out)


# ------------------------------------------------------------------------- the predicate

def test_the_evidence_is_two_hops_away_and_behind_a_component():
    """Measured on r26, where a one-hop <input>-only predicate judged all five real lane
    revisions dead: the page holds neither half of the evidence, the /auth/login literal is
    two hops out in services/api, and the named control is a <TextInput> component."""
    fe = _tree(_LANE_PAGE)
    target = fe / "src" / "pages" / "LoginPage.jsx"
    assert fs._lane_auth_page_is_live_1197(_LANE_PAGE, target) is True

    # Cut the second hop: the call remains, the endpoint no longer exists anywhere.
    (fe / "src" / "services" / "api.js").unlink()
    assert fs._lane_auth_page_is_live_1197(_LANE_PAGE, target) is False


def test_an_earlier_framework_projection_is_not_mistaken_for_the_lane(monkeypatch):
    """#1179b gives the projection named inputs and it posts to /auth/login, so it satisfies
    this fix's OWN predicate — r26's 72-line framework page did, measured. Without provenance
    the framework would defer to its own previous output and freeze the auth page against
    later template work (#526/#540/#1179 all land through it)."""
    monkeypatch.delenv("ENVGEN_DEFER_TO_LANE_PAGE", raising=False)
    fe = _tree()                      # no page yet -> first pass projects and records
    first = _run(fe)
    assert _is_framework_projection(first)

    improved = first + "\n// a later template improvement\n"
    monkeypatch.setattr(fs, "_project_page_component", lambda *a, **k: improved)
    assert _run(fe) == improved       # not frozen at `first`


def test_provenance_is_recorded_per_page_and_only_matches_what_we_wrote(tmp_path):
    fe = tmp_path / "app" / "frontend"
    (fe / "src" / "pages").mkdir(parents=True)
    assert fs._is_our_auth_projection_1197(fe, "LoginPage", "anything") is False
    fs._remember_auth_projection_1197(fe, "LoginPage", "PROJECTION-A")
    assert fs._is_our_auth_projection_1197(fe, "LoginPage", "PROJECTION-A") is True
    assert fs._is_our_auth_projection_1197(fe, "LoginPage", "PROJECTION-B") is False
    assert fs._is_our_auth_projection_1197(fe, "SignupPage", "PROJECTION-A") is False


def test_an_empty_or_unreadable_page_is_never_live():
    assert fs._lane_auth_page_is_live_1197("", Path("/nonexistent/LoginPage.jsx")) is False
    assert fs._lane_auth_page_is_live_1197("   \n", Path("/nonexistent/LoginPage.jsx")) is False


# ------------------------------- #1199b: deferring means inheriting the session contract

def test_a_login_that_never_persists_the_session_is_still_replaced(monkeypatch):
    """The projection this defers to stores the token — its template says so, and every
    projected page reads `localStorage.getItem('access_token') || localStorage.getItem('token')`.
    A lane login that posts credentials and stores nothing would pass the first two conditions
    and leave every projected page unauthenticated: #1108 exactly, where the token went to a
    key nobody read (401s 17 -> 0 once fixed)."""
    monkeypatch.delenv("ENVGEN_DEFER_TO_LANE_PAGE", raising=False)
    no_store = (
        "export async function login(email, password){\n"
        "  return fetch('/auth/login', {method:'POST'}); }\n")
    fe = _tree(_LANE_PAGE, form_src=_WIRED_DRIVABLE)
    (fe / "src" / "services" / "api.js").write_text(no_store, encoding="utf-8")
    out = _run(fe)
    assert out != _LANE_PAGE
    assert _is_framework_projection(out)


# ------------------- #1202e: a second line of defence behind the provenance sidecar

def test_the_frameworks_own_template_is_recognised_by_content(monkeypatch):
    """The predicate cannot tell our page from a lane's on content alone — the projection is
    wired, drivable and persists by construction. Until now everything therefore rested on
    `auth_projections_1197.json` being present, and a resumed run whose design/ directory was
    rebuilt would have seen the framework defer to its OWN page and freeze it against every
    later template fix.

    Measured over every auth page in the corpus (207 framework-written, 35 lane-written), the
    template's `const path = isRegister ? ...` line appears in 204 of the 207 and 0 of the 35.
    Applying it drops the wrong "keep" verdicts from 23 to 2 while leaving all 12 correct ones.

    #1197 concluded a fingerprint "cannot work either". That was the wrong conclusion from a
    real observation: the fingerprint tried was "the longest substitution-free line", which
    picked a footer r26's page did not carry.
    """
    monkeypatch.delenv("ENVGEN_DEFER_TO_LANE_PAGE", raising=False)
    fe = _tree(_LANE_PAGE)
    target = fe / "src" / "pages" / "LoginPage.jsx"

    line = fs._auth_template_line_1202e()
    assert line.startswith("const path = isRegister"), line

    # A lane page that happens to be wired, drivable and persisting is kept ...
    assert fs._lane_auth_page_is_live_1197(_LANE_PAGE, target) is True
    # ... and the same page with the framework's own line in it is not.
    assert fs._lane_auth_page_is_live_1197(_LANE_PAGE + "\n" + line, target) is False


def test_the_marker_is_derived_from_the_template_not_retyped():
    """#905/#906: one predicate spelled twice drifts on the first edit to either."""
    src = (Path(__file__).resolve().parents[1]
           / "env_generator/llm_generator/multi_agent/runtime/frontend_scaffold.py"
           ).read_text(encoding="utf-8")
    at = src.index("def _auth_template_line_1202e")
    ends = [e for e in (src.find("\ndef ", at + 10), src.find("\n# ---", at + 10)) if e > 0]
    body = src[at:min(ends)]
    assert "_AUTH_PAGE_TEMPLATE" in body
    # Only the CODE may not re-type it; the docstring quotes the line as its evidence.
    code = body.split('"""', 2)[-1]
    assert "'/auth/register'" not in code
