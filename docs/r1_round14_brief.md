# R1 Round-14 Routing Brief — Pilot Classifier Re-Gate

> **State**: post round-5 internal-adversarial cleanup + spec §6 layer-2
> freeze criterion landed. `CLASSIFIER_SPEC_SHA = "a048316b-draft"` —
> NOT bumped. Awaiting R1 round-14 verdict on the §6.1 criterion.
>
> **R1 round-13 explicit framing**: *"round-14 我的最终 gate 重点会放在
> layer-2 的证明上(ITT 重算确实 bound 住、asymmetry gate 确实 fire、
> claim 确实 gated on ITT-worst-case),而不是去抓 signature 第 N+1 个
> 洞"*. This brief is structured for that framing.

---

## 1. Why this brief is the right shape (R1 + R2 round-13 convergence)

Both reviewers independently diagnosed the iteration pattern as
**layer-1 denylist grind**:

- R1: *"env-signature 这套架构…本质上是一个 denylist。denylist 永远不可能
  枚举完全：你见过的失败模式能加进去，下一个没见过的生成-app 失败模式会
  产出第 N+1 个洞…round-5 的 \"vocabulary code-wide scan 一次扫干净\" ——
  仍然是 layer-1 思维"*
- R2: *"对抗生成器永不返回空…round-5 的 scope (vocabulary 扫 + 删 legacy
  路径) 本身就证明你已经到噪声地板了 —— 对抗 agent 被指派 \"找
  over-exclude\"，在干净代码上也总会 surface 一条边际的，但那条现在是
  hygiene，不是 laundering"*

Both pointed at the same structural answer: **trust layer-2** —
ITT-worst-case + asymmetry gate — and freeze when V is green + residual
is immaterial + the §5.1 backstop is in position. Demanding zero-residual
underuses the backstop and never converges. Same shape as Phase 0.2's
one-line fail-closed default breaking the 8-round attempt cycle.

**The §6 amendment in commit `e50fe23f` codifies this as the standing
freeze criterion** — so future-me / future-R1 / future-R2 don't repeat
the same grind on the next gate. This brief asks R1 round-14 to verdict
on the §6.1 criterion (layer-2 proof), not on signature N+1.

---

## 2. Substance arc — 5 internal adversarial rounds (depletion proof)

| Round | Source | Finding(s) | Class |
|---|---|---|---|
| R1 round-12 | external | B-1 daemon_down + B-2 image_pull + B-3 oom + B-4 disk_full + B-5 buildkit + B-6 daemon_5xx + B-7 step-0 + latent port_conflict + **B-8 §5.1 data shape** | structural |
| internal r1→2 | internal | B-2 dockerd-marker + B-5 RUN-line shape | tightening |
| internal r2→3 | internal | buildkit_recurrence raw_evidence concat | channel uniformity |
| **R1 round-13** | external | env.oom B-3a OOMKilled=False not vetoed + B-3b raw_evidence channel exception | structural (env.oom) |
| **R2 round-13** | external | mem_limit injection by-construction (CONSTRAINT_NONE ambiguity) | structural (R2 predicted this would be the LAST load-bearing semantic hole) |
| internal r4→5 | internal | `_check_daemon_down` legacy back-compat path = active rationalization on env-positive | **dead-code hygiene** (R2's predicted floor) |

R2 round-13 explicit prediction: *"mem_limit 那条 (round-4) 大概率就是
最后一条 load-bearing 语义洞；之后都是地板"*. Round-5 realized that
prediction: the only finding was dead-code rationalization, removed
without flipping any fixture verdict.

**Substance is monotonically depleting; count plateau is the adversarial
generator's noise floor on clean code.**

---

## 3. §6.1 criterion verification (R1's actual round-14 ask)

### (1) V-fixtures all green ✓

```
classifier_acceptance:  67/67  (30 R1-original + 22 r1 remediation
                                + 4 r2 + 4 r3 + 6 r4 env.oom + 1 r5)
itt_recompute:          11/11
north_star/ dir invoke: 100 passed (incl 18 subtests)
runhub_compose:          8/8
dockerfile_lint:        11/11
spike arm_1a:           passes (regression preserved across all rounds)
```

★ launder-trap stars all green; positive controls all green; by-construction
preconditions (`runner_injected_mem_limit=None → FUNCTIONAL`, static port →
`INADMISSIBLE → FUNCTIONAL`) all pin.

### (2) Residual is immaterial / hygiene only ✓

Round-5 code-wide rationalization scan across 4 files
(classifier.py, runner.py, spec, conftest.py):

- **Zero active rationalizations** on env-positive determination paths.
- **10 surviving vocabulary hits** all classified:
  - 5× **CLOSED reference** comments (each comment verified against current code reality — describes a past hole that the code structurally closed; not a current weakener).
  - 5× **non-env-positive** paths (run_id default, sink env-var spike-shim, teardown project default, etc — cannot promote a verdict to env).

No new semantic class found across rounds 4-5. Round-5's only finding was dead code (R2-predicted floor).

### (3) §5.1 backstop in position and decisive-tested ✓

`compute_itt_delta` (classifier.py:962-997) returns BOTH rates per
comparison. Asymmetry gate constants pinned (`ASYMMETRY_REL_X = 2.0`,
`ASYMMETRY_ABS_PP = 5.0`) at L985-986. Decisive tests:

- `test_itt_advantage_does_not_survive_blocked_by_asymmetry`: planted
  40pp env-exclusion gap on the new arm with an artificially-inflated
  as-classified rate. ITT recount evaporates the advantage; asymmetry
  gate fires `blocked=True`. ✓ Pinned green.
- `test_itt_asymmetry_trigger_blocks_on_small_gap`: 10pp gap triggers
  the absolute threshold. ✓ Pinned green.

R1's own round-13 verification quote: *"我刚 first-hand 确认它有决定性
的两个性质…决定性测试都在…✓"*. The backstop is real; this brief asks
R1 to revalidate at round-14 with adversarial inputs of R1's choice.

### (4) Wins gated on both rates ✓

§5.1 codified the rule. `compute_itt_delta`'s return dict carries
both `as_classified.{old,new,delta}` and `itt.{old,new,delta}`;
downstream B1 §9.6 consumers MUST gate `win = as_classified_delta > 0
AND itt_delta > 0 AND NOT blocked_by_asymmetry`.

**The pre-registered constraint is fixed in §5.1 and §6.1; B1 must
honor it. The data shape is enforced in `Verdict.to_dict()` and
`compute_itt_delta`'s schema — B1 cannot consume the data without
also consuming the constraint.**

---

## 4. What R1 should adversarial-verify at round-14 (per R1's framing)

Per R1 round-13: round-14 gate is layer-2 proof, not signature N+1.

Suggested attack vectors (R1's choice of which to run):

1. **Plant a layer-1 signature leak** on a synthetic JSONL sink (e.g. a fixture where an app-fault was wrongly classified as env on 30% of new-arm runs). Verify:
   - as-classified delta would show new-arm "advantage"
   - ITT recount evaporates it ← the load-bearing property
   - asymmetry gate fires if exclusion asymmetry exceeds threshold

2. **Asymmetric exclusion at exactly the threshold boundary**: 4.9pp absolute gap (should not block); 5.1pp gap (should block); 1.99× relative ratio (should not block); 2.01× (should block). Confirm boundary behavior is sharp, not fuzzy.

3. **Win-on-one-rate-but-not-other**: as-classified shows new-arm +3pp; ITT shows new-arm -2pp. Confirm the downstream contract treats this as NOT a win (constraint is in spec §5.1; impl is in B1 territory but the constraint is fixed here).

4. **Surface-level signature check** (optional, since R1 said round-14 is layer-2): pick any one new V-fixture from round-3/4/5 and confirm the verdict; verify the cleanup-discipline check (any verdict flip on existing fixtures during round-5 cleanup = blocker — by direct re-run, none).

5. **§6.1 criterion text itself**: does the wording capture the intent? Is "hygiene only" defined precisely enough that future R1/R2 sessions can apply it without ambiguity? The current text classifies findings into {new semantic class / active rationalization / vocabulary variant / dead-code hygiene}. R1 may want to refine.

---

## 5. Commits in the freeze ledger

```
e50fe23f  feat(north-star): round-4/5 env.oom + daemon_down cleanup + spec §6 layer-2 freeze criterion
de05b9a9  feat(north-star): R1-gate remediation rounds 1-3 + internal-adversarial CLEAR
102ce90b  feat(north-star): runner instrumentation + ephemeral ports + [POPULATE]
00ce5a12  feat(north-star): pilot failure classifier — impl + 27 V-fixture acceptance tests
de5aa82e  docs(ext-register): canonical EXT register — single source of truth
a048316b  docs(pilot): pre-registration classifier spec — DRAFT (R2 author, R1 gate pending)
```

`CLASSIFIER_SPEC_SHA = "a048316b-draft"`. R1 round-14 CLEAR → FREEZE SHA-pin commit bumps to `e50fe23f` (or the tip at R1-CLEAR time). The freeze pin is the next commit, not in `e50fe23f`.

---

## 6. Asks of R1 (round-14)

- **Primary**: verdict §6.1 criterion (1)-(4). Are all four satisfied?
- **Secondary**: any active rationalization the round-5 scan missed (independent grep).
- **Tertiary**: §6.1 criterion text precision — does it bind tightly enough for future sessions?

If CLEAR → human routes back to builder → FREEZE SHA-pin commit lands → pipeline-generate simple_blog → calibration arm on real generated app.

If BLOCKED → triage per §6.2: vocabulary variant / dead-code hygiene → fix inline, not a freeze blocker; new semantic class → fix one, freeze; active rationalization → remove, freeze.

R2 stands by for verification of any R1-flagged change (R2 round-13's behavior-preservation discipline: cleanups must not flip fixture verdicts; bidirectional fixtures required for any path change).
