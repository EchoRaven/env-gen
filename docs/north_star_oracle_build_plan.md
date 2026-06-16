# North-Star Oracle Build — Plan

> Status: **PROPOSAL** — waiting on sign-off before code work.
> Sub-project of `docs/progressive_elaboration_refactor.md` §9 (North-Star
> Quality Baseline). Reviewer's exact framing: "treat as a real sub-project,
> not a checkbox; §9.1.5 (oracle double-validation) is the make-or-break part."

## 0. tl;dr

Build the three reference specs + their **independent functional test oracles**
that the §9.1 north-star metric depends on. Without this infrastructure, **no
later phase can claim quality improvement** — only "mechanism shipped".

Scope: ~1000 LOC per spec × 3 specs ≈ ~3000 LOC over the whole sub-project.
Plus a per-spec ~200 LOC validation harness (§9.1.5: known-good + known-broken).
Recommended ordering: ship `simple_blog` end-to-end first, validate the pattern,
then clone for `twitter_clone` and `simple_ecommerce`.

## 1. What the oracle is, and what it is NOT

The oracle is **NOT** another test in `tests/`. Existing `tests/` are unit-level,
agent-internal contracts. The oracle is **EXTERNAL** — it exercises a running
generated app as a black-box user.

| | What it is | What it is NOT |
|---|---|---|
| Where it lives | `tests/north_star/<spec>/oracle/` | not a unit test, not in agent-code |
| What it talks to | HTTP at `:<api_port>` + browser at `:<ui_port>` | not any internal Python API |
| What it knows | Only the spec's user-visible contract (endpoints, pages, flows) | NOT the impl, NOT the schema, NOT internal data shapes |
| Who writes it | A human (me, with reviewer audit) — pinned and reviewed like production | NOT an LLM agent, NOT regenerated, NOT consumed by any agent |
| When it runs | Every north-star measurement run | NOT during the agent loop, NOT visible to agents |

**Crucial invariant**: the LLM agents in the pipeline must NEVER see the oracle's
source. Per §9.1: "an independent oracle the LLM agents never see and cannot game."

Enforcement (light, defense-in-depth — not load-bearing):
- Oracle lives at `tests/north_star/<spec>/oracle/`
- Agent prompts will be checked (lint-style) to not include `tests/north_star/`
- `north_star/` is added to ignored-prompt-context lists
- If an agent ever explicitly requests it, refuse + audit

## 2. Directory layout

```
agent/tests/north_star/
  __init__.py                          # marks as package
  conftest.py                          # shared fixtures: start_app, ports, http client
  runner.py                            # entry point: run an oracle against an app

  simple_blog/
    SPEC.md                            # the prompt fed to the pipeline (input)
    reference_impl/                    # hand-written correct app
      docker-compose.yml
      backend/                         # FastAPI + SQLite
        main.py
        models.py
        requirements.txt
        Dockerfile
      frontend/                        # plain HTML + minimal JS (Vite optional)
        index.html
        app.js
        Dockerfile
      database/
        init.sql
    oracle/
      __init__.py
      test_register.py                 # flow 1: register a new user
      test_login.py                    # flow 2: login + session
      test_create_post.py              # flow 3: create a post (auth required)
      test_edit_post.py                # flow 4: edit own post
      test_view_post.py                # flow 5: view a post (incl. unauth read)
      test_delete_post.py              # flow 6: delete own post
    oracle_validation/                 # §9.1.5
      __init__.py
      test_validation.py               # runs oracle against reference_impl + against
                                       # broken variants; asserts oracle is calibrated

  twitter_clone/   (same shape)
  simple_ecommerce/   (same shape)
```

Total ≈ 30-40 files per spec, ~1000 LOC.

## 3. Per-spec design

### 3.1 simple_blog

**Spec summary** (full text in `SPEC.md` once committed):
- Single-author blog. Users register → login → write/edit/delete posts.
- Anyone (auth or not) can read posts; only the author can write/edit/delete.
- ≤6 endpoints, ≤4 pages.

**Critical flows** (the 6 in §9.2):
| # | Flow | API endpoints exercised | UI pages touched |
|---|---|---|---|
| 1 | `register` | `POST /register` | `/register`, redirect to `/` |
| 2 | `login` | `POST /login` | `/login`, cookie set |
| 3 | `create_post` | `POST /posts` | `/posts/new`, redirect to `/posts/<id>` |
| 4 | `edit_post` | `PUT /posts/<id>` (own) | `/posts/<id>/edit` |
| 5 | `view_post` | `GET /posts/<id>` (unauth ok) | `/posts/<id>` |
| 6 | `delete_post` | `DELETE /posts/<id>` (own) | `/`, post no longer shown |

**Negative cases each flow MUST cover** (so the oracle isn't just happy-path):
- `register`: duplicate email → 400; weak password rules (if specified) → 400
- `login`: wrong password → 401; missing cookie after login → fail
- `create_post`: unauthenticated → 401; empty body → 400
- `edit_post`: not-the-author → 403; nonexistent id → 404
- `view_post`: nonexistent id → 404
- `delete_post`: not-the-author → 403; double-delete → 404

Each oracle test asserts BOTH the happy path AND at least one negative case.

### 3.2 twitter_clone

Same shape; flows: register / login / post / like / follow / followed-only-feed.

Negatives:
- `follow`: self-follow → 400; non-existent user → 404
- `like`: double-like idempotent (200 or 400, consistent); unauth → 401
- `feed`: only followed users' posts; chronological order; pagination if specified

### 3.3 simple_ecommerce

Same shape; flows: browse / add-to-cart / checkout / order-history.

Negatives:
- `add_to_cart`: out-of-stock → 400
- `checkout`: empty cart → 400; no payment integration (mocked)
- `order_history`: only own orders; unauth → 401

## 4. reference_impl architecture

**Stack** (chosen for hand-write speed, NOT to match the LLM-generated stack):

- Backend: **FastAPI** (Python 3.11+)
  - Auth: stdlib `secrets.token_urlsafe` + httpOnly cookie
  - Password hashing: `hashlib.scrypt` (stdlib, no extra dep)
  - DB driver: `sqlite3` (stdlib)
- Frontend: **plain HTML + vanilla JS** (no React/Vue/etc.)
  - Forms post directly; JS only where needed for dynamic loading
  - Why: hand-writing 4 pages of React for the reference takes 3x longer for no benefit; the oracle exercises HTTP behavior, not framework choice
- Database: **SQLite** (file-backed in container, or `:memory:` for tests)
- Container: **docker-compose** matching pipeline's output shape so the
  `start_app` fixture works the same way for reference and generated apps

**Why hand-write the reference**:
1. The oracle's calibration depends on a known-correct artifact. An LLM-written reference would defeat the purpose (oracle calibrated against LLM output is circular).
2. The reference is small (≤400 LOC backend, ≤200 LOC frontend) — fast to hand-write.
3. Reference is the LONG-TERM artifact; quality matters more than speed.

## 5. Oracle architecture

**One test file per critical flow.** Inside each: ≥2 test methods (happy + negative).

```python
# tests/north_star/simple_blog/oracle/test_create_post.py
import requests
from playwright.sync_api import sync_playwright

def test_authenticated_user_can_create_post(api_url, ui_url):
    """Happy path: register → login → POST /posts → see in /posts list."""
    s = requests.Session()
    s.post(f"{api_url}/register", json={"email": "a@x.com", "password": "pw12"})
    s.post(f"{api_url}/login", json={"email": "a@x.com", "password": "pw12"})
    r = s.post(f"{api_url}/posts", json={"title": "hi", "body": "world"})
    assert r.status_code == 201
    post_id = r.json()["id"]
    listing = s.get(f"{api_url}/posts").json()
    assert any(p["id"] == post_id for p in listing["posts"])

def test_unauthenticated_post_creation_is_rejected(api_url):
    r = requests.post(f"{api_url}/posts", json={"title": "x", "body": "y"})
    assert r.status_code == 401
```

**Fixtures** (`conftest.py`):
- `app_under_test(spec_name)` — Tuple[api_url, ui_url]. Starts the docker-compose for either:
  - `reference_impl` (for validation, baseline runs)
  - A `--app-path=` cmdline arg pointing at a pipeline-generated workspace (for measurement runs)
- Captures container ports (the existing pipeline already does port pinning via `run_budget.json`; oracle reuses that infrastructure where possible).
- Tears down on test session end.

**Independence from agent code**: the oracle imports `requests`, `playwright`, `pytest`. It imports NOTHING from `env_generator/`.

## 6. §9.1.5 — Oracle double-validation (the make-or-break part)

This is the test SUITE for the oracle itself. Lives at
`tests/north_star/<spec>/oracle_validation/test_validation.py`.

Per-spec validation harness:

```python
class OracleCalibrationTests(unittest.TestCase):
    def test_oracle_passes_against_reference_impl(self):
        """Known-good: the hand-written reference_impl must pass 6/6 flows."""
        result = run_oracle_against(reference_impl_path)
        self.assertEqual(result.flows_passed, 6)
        self.assertEqual(result.flows_failed, 0)

    def test_oracle_catches_broken_create_post(self):
        """Known-broken: remove the POST /posts handler. The
        create_post flow must fail; the other 5 must still pass."""
        with broken_variant(remove_handler="POST /posts"):
            result = run_oracle_against(broken_impl_path)
        self.assertEqual(result.flows_failed, 1)
        self.assertEqual(result.failed_flow_names, ["create_post"])

    def test_oracle_catches_broken_auth(self):
        """Different break: weaken auth so unauthenticated calls succeed.
        Multiple flows' negative cases catch this."""
        with broken_variant(disable_auth_check=True):
            result = run_oracle_against(broken_impl_path)
        # negative cases in create_post, edit_post, delete_post all fail
        self.assertGreaterEqual(result.flows_failed, 3)
```

**Three failure modes the validation must catch**:
1. Oracle too lenient (broken impl → still 6/6 pass) — calibration too loose
2. Oracle too entangled (one break cascades into unrelated flows failing) — flow coupling
3. Oracle stuck on env (oracle never starts the app, always passes/fails) — fixture bug

The `broken_variant(...)` context manager makes a minimal source-level edit to
the reference_impl (e.g. comment out a handler, change a status code, drop a
session check) and runs the oracle. The edit is reverted at context exit.

### 6.X — Cross-stack calibration arm (R2 round-5, the make-or-break-of-the-make-or-break)

Per R2's round-5 plan-review delivery (the A1 piece): the original
double-validation only proves the oracle is calibrated against its OWN
reference_impl. If the pipeline produces a different but spec-compliant
stack (Bearer auth instead of cookie, `/api` prefix instead of bare,
`201 Created` instead of `200 OK`, `{"items": [...]}` envelope instead
of bare list), the oracle will systematically FALSE-FAIL the generated
app — making improvements LOOK like regressions to the north-star metric.

This is the "make-or-break circle": oracle calibrated against ref_impl
+ ref_impl is correct + generated app uses different conventions →
oracle says generated app is broken → north-star metric is poisoned.

R2 verified the pipeline really does diverge from the FastAPI/cookie
reference: `project_structure.py:152` declares "auth method (JWT
Bearer)", `:267` declares "frontend uses `/api` and nginx reverse-proxies
`/api/*` to backend".

**MANDATORY** validation arm #3 (alongside known-good + known-broken):

```python
def test_oracle_passes_against_a_real_generated_app(self):
    """Cross-stack calibration: oracle MUST go 6/6 against a real
    pipeline-generated app (Bearer + /api), not just the FastAPI/cookie
    reference. If this fails: oracle has convention coupling, not
    behavior coverage."""
    result = run_oracle_against(PINNED_GENERATED_APP)  # demos/* known-good
    self.assertEqual(result.flows_failed, 0,
        "oracle false-fails a correct generated app — "
        "convention coupling, not behavior")
```

Implementation: every per-spec oracle imports from
`tests/north_star/_conventions.py` (R2 round-5 delivery, landed
verbatim) which provides the convention-tolerant helpers:

- `authenticate(session, base, email, password)` — accepts both cookie
  (reference) and Bearer (pipeline) auth; pulls token from response
  body if present, falls back to cookie persistence otherwise.
- `resolve_base(api_url, app_path)` — reads `spec.api.json` conventions
  block (`base_url`) when available; probes `/health` and `/api/health`
  otherwise. Single resolution per app.
- `assert_unauthorized(resp)` — accepts both 401 and 403.
- `assert_client_error(resp, expect=None)` — 400/422 treated synonymous;
  insists on JSON body (catches "200 with HTML app shell" anti-pattern).
- `assert_created(resp)` — accepts 200 or 201; extracts id with 1-level
  wrapper tolerance.
- `_id_of(obj)` / `items_of(listing)` — tolerates `{id, _id, uuid, pk}` +
  `{data, result, post, item}` wrappers + `{posts, items, data, results}`
  list envelopes.

**Principle**: tolerate the CONVENTION strictly, never the BEHAVIOR.
Over-loosening behavior assertions blinds the oracle and misses real
bugs. The convention helpers above are the canonical surface — any
per-spec oracle adding its own loose assertion (e.g. "any 2xx is fine")
is REJECTED at oracle code-review.

**Where `PINNED_GENERATED_APP` comes from**: a known-good app produced
by the pipeline on a stable commit, checked into `demos/` or fetched
by SHA. Pinned to avoid flaky changes in the generator from invalidating
the calibration arm.

**An oracle that doesn't pass ALL THREE validation arms (known-good 6/6,
known-broken catches-exactly-1, AND cross-stack pinned-generated 6/6)
CANNOT drive north-star metrics.**

## 7. Estimated effort + ordering

### simple_blog (PILOT — must finish before others start)

| Step | Effort | What |
|---|---|---|
| 1. SPEC.md | 0.5 day | Detailed app spec, written for the pipeline to consume |
| 2. reference_impl backend | 1 day | FastAPI + SQLite + auth + 6 endpoints |
| 3. reference_impl frontend | 0.5 day | 4 plain HTML pages + minimal JS |
| 4. reference_impl docker-compose | 0.5 day | Same shape pipeline produces |
| 5. conftest.py + runner.py | 1 day | Fixtures: start_app, ports, session |
| 6. 6 oracle flow files | 1.5 days | ~6 × ~100 LOC each, happy + ≥1 negative |
| 7. oracle_validation harness | 1 day | broken_variant context + 3 calibration tests |
| 8. Run + fix anything | 0.5 day | Make sure 6/6 green on known-good, broken caught on each variant |
| **subtotal** | **~6.5 days** | |

### twitter_clone + simple_ecommerce (after pilot)

Once `simple_blog` ships and the pattern is proven:

| Spec | Reuse from pilot | New work | Effort |
|---|---|---|---|
| twitter_clone | runner + conftest pattern + validation harness | spec + impl + 6 oracles + broken variants | ~4 days |
| simple_ecommerce | same | same | ~4 days |

**Total**: ~14-15 days of focused work. Two-thirds is the pilot.

This is workflowable in places but mostly needs careful hand-engineering on
the reference_impl + the oracle calibration. Per reviewer: not a fan-out
problem.

## 8. Acceptance gate for "north-star ready"

The §9 baseline (90-cell csv) cannot be measured until:

| Gate | Status |
|---|---|
| All 3 specs have committed `SPEC.md` | ⏳ |
| All 3 specs have reference_impl that runs (`docker compose up` returns healthy) | ⏳ |
| All 3 specs have oracle suites with ≥6 flow tests each (happy + negative) | ⏳ |
| All 3 specs pass `oracle_validation` arms 1+2: known-good 6/6 + known-broken catches-exactly-1 | ⏳ pilot scope |
| All 3 specs pass `oracle_validation` arm 3 (R2 round-5): cross-stack calibration against PINNED_GENERATED_APP | ⏳ **PILOT WORK, not pre-pilot.** R2 round-6 correction: the calibration arm cannot exist before the oracle does. _conventions.py is the scaffolding; the arm itself = pilot scope. |
| Convention helpers in `tests/north_star/_conventions.py` reviewed + locked | ✅ landed attempt-6 (R2 verbatim) + R2 round-6 fix (`assert_created` raises on missing id, no longer silently returns None) + 22-case self-test in `tests/north_star/test_conventions_self.py` |
| `tests/north_star/runner.py` works against both reference_impl AND a generated app dir | ⏳ pilot scope |

**R2 round-6 honesty correction**: attempt-6's summary message claimed "A1 LANDED VERBATIM ✅" — that was overstated. What landed in attempt-6 (commit `a1d1d739`) was the SCAFFOLDING:
  - `_conventions.py` helpers (cookie-or-Bearer, /api prefix, {401,403}, etc.)
  - A2 collection isolation (`conftest.py` collect_ignore)
  - `north_star_oracle_build_plan.md` §6.X documenting the calibration arm

What did NOT land:
  - NO `run_oracle_against` function
  - NO `PINNED_GENERATED_APP` fixture
  - NO `demos/` infrastructure
  - NO per-spec oracle (simple_blog, twitter_clone, ecommerce)
  - NO `runner.py`
  - NO `reference_impl/`
  - NO `broken_variant()` context manager

The cross-stack calibration arm is documented in §6.X but is NOT
implementable until the oracle infrastructure exists. The arm IS the
pilot work — specifically, validating that the oracle (when it exists)
isn't calibrated only to its own reference. It cannot be a pre-pilot
deliverable because there's nothing to calibrate.

attempt-6 commit `a1d1d739`'s "A1 LANDED VERBATIM" wording was a
self-deceptive claim. The §11.2.5 discipline applies to docs too:
honest framing first, then ship.

Only then can we run the 90-cell baseline. **No earlier.**

## 9. Risks + mitigations

| Risk | Mitigation |
|---|---|
| Oracle calibration too lenient → false-green north-star | §9.1.5 known-broken variants catch this; multiple broken types per spec |
| reference_impl has its own bug → oracle calibrated incorrectly | Adversarial code review by reviewer on each reference_impl PR; treat reference_impl like production |
| Port collisions when oracle runs alongside other generation work | Fixture uses pipeline's port-pinning infrastructure (already exists in `run_budget.json`); fall back to OS-allocated ports |
| Spec drift between SPEC.md and reference_impl | Reference_impl tests itself against the oracle in CI; if reference_impl drifts from spec, this catches it |
| Spec drift between SPEC.md and what the pipeline generates | The whole point of the north-star is to measure this gap. Not a risk; the metric. |
| Generation-time env failures (docker port collision, OOM) drowning the signal | §9.6 env-failure exclusion rule; failures classified into bug / fallback-used / env-failure |
| LLM agents inadvertently see the oracle | `tests/north_star/` excluded from all prompt-context paths; lint rule on agent prompts to confirm |

## 10. Decisions needed before code starts

a. **Stack confirmation**: FastAPI + plain HTML + SQLite for reference_impl. The pipeline today generates a different stack (need to check — likely Node + React + Postgres or similar). Is it OK that the reference_impl stack differs from the pipeline's output, since the oracle is HTTP/UI-level?

b. **Pilot scope**: 6 critical flows for `simple_blog`. Reviewer's §9.2 lists 6 in the catalog. OK to start with exactly these 6?

c. **Negative-case rigor**: I'm proposing ≥1 negative case per flow (so 12+ tests per spec). Per spec calibration would catch most regressions but means each flow file is bigger. OK?

d. **Validation breakage catalog**: at least 3 known-broken variants per spec (one removes a handler, one breaks auth, one breaks a status code). More = better calibration but more authoring effort. Floor of 3 acceptable?

e. **Timing**: ~6.5 days for the pilot (simple_blog) before we can even start the cumulative baseline. Phase 1 is BLOCKED on this finishing. Is the ~3 week total horizon to north-star-ready acceptable, or should we descope (e.g., 1 spec instead of 3)?

f. **My role**: I'd ship this as concrete commits (NOT a workflow fan-out — per reviewer "not a checkbox"). Each step is reviewable in isolation: spec → reference_impl → oracle flows → validation. Want me to ship pilot for `simple_blog` step-by-step with PR-style reviews, or batch?

## 11. Open question (mine, for reviewer)

Reviewer pointed out: "Budget for the ~15 baseline generation runs being flaky
(deadlocks/env failures) and needing the §9.6 env-failure exclusion before the
means are trustworthy."

Concrete question: if env-failure rate is ≥30% (which is plausible given
LaneIdleCircuitBreaker history), the 5-run-per-spec sample after exclusion
could leave fewer than 3 usable runs per cell. Should we raise the floor to
**n=10 baseline runs per spec** to ensure ≥5 usable after exclusion? This
multiplies baseline cost (~30 runs instead of 15) but protects the statistic.

If env-failure rate is <10% (best case), n=5 is fine.

I'd recommend n=10 as the safe default; if first 5 runs come in clean, drop
back to n=5 for later phases.

---

## Appendix — Where this fits in the overall plan

This sub-project sits AFTER Phase 0.2 completes (per reviewer's sequencing):

```
Phase 0.1 ✅ SHIPPED
Phase 0.2 ✅ SHIPPED (narrow scope, 2026-05-30 round-8 both-reviewer ACCEPT)
[Cross-stack calibration spike] ⏳ NEXT (1 day, de-risks the pilot — both R1+R2 recommend)
[Oracle build / pilot] ⏸️ gated on spike outcome
  ├─ simple_blog pilot (~6.5 days)
  ├─ twitter_clone (clone of pilot, ~4 days)
  └─ simple_ecommerce (clone of pilot, ~4 days)
[Baseline (A) measurement] — runs against checkout of 9ba65c35
                            (the commit-pinned pre-refactor anchor;
                            §9.4 R2 round-5 A3 fix)
[Baseline (B) per-phase A-B] — runs against post-0.2 HEAD vs phase=N-1
                               (the incremental delta; §9.4)
Phase 1 — needs baseline (A) + baseline (B) for Phase 0.2→1 → quality story
Phase 2 — same
... etc
```

**R2 round-5 A3 correction (this Appendix originally said "runs ON
POST-0.2 HEAD")**: that conflated baseline (A) with baseline (B).
- (A) = absolute pre-refactor — runs against `9ba65c35` (commit-pinned).
- (B) = per-phase incremental — runs against post-0.2 HEAD with the
  `ELABORATION_REFACTOR_PHASE` flag toggled between `=N-1` and `=N`.

These are different measurements; they answer different questions and
have different anchors. See plan doc §9.4 for the full split.
