"""Substance check for kickoff section decisions — shared by the agent-side
corrective loop (messaging) and the facilitator's phase gate (facilitate).

gemini exhibits three authoring failure shapes: MALFORMED tool calls (dropped),
empty shells ({"ui_pages": []}), and null-placeholder skeletons
([null, null, ...]). All three must read as NOT AUTHORED — otherwise they
satisfy existence checks and starve the synthesis (live 2026-06-10: the
meeting finalized on five empty frontend decisions two seconds before the
corrective turn could land a real one)."""

from __future__ import annotations

from typing import Any, Mapping

_META_KEYS = ("section", "kind", "recorded_by", "agent", "recorded_at",
              "milestone_index", "round")

# The contract keys each section legitimately declares. ``data_model``/``tables``
# both appear because the backend nests tables under data_model. Used to tell a
# "submitted the wrong thing" payload (only non-contract keys, e.g. the
# framework-owned auth_model) apart from a truncated/empty one — see
# ``non_contract_keys``.
_RECOGNIZED_KEYS = {
    # user_flows RETIRED from the frontend section (user directive 2026-06-22): a
    # user_flow is NOT a frontend-kickoff artifact — critical flows are derived from
    # the registered CONTRACT (ui_pages + endpoints), see test_user_squad +
    # flow_coverage. The frontend declares ui_pages + ui_components only.
    "frontend": ("ui_pages", "screens", "ui_components"),
    "backend": ("endpoints", "data_model", "tables"),
    "verifier": ("predicates",),
}

# AUXILIARY kickoff fields a section legitimately records via the generic
# workhub_add_meeting_decision tool — there is NO kickoff_declare_* tool for
# them. The frontend prompt's FINAL PROTOCOL step 4 instructs exactly this
# ("one small add_meeting_decision for the scalar fields: auth, done_def"), and
# the reconcile/synthesis READS them (run_kickoff: done_def floor +
# _pick_feature_inventory). They are NOT buildable substance (section_has_substance
# still ignores them, so they don't advance the phase) but they are NOT
# non-contract garbage either: a decision carrying ONLY these must be ACCEPTED,
# not rejected into an 18× resend loop (run bsb900gpt). Auth (auth/auth_model)
# is deliberately EXCLUDED — it is framework-owned and a real wrong-keys signal
# (youtube run #13). Prefix match absorbs the LLM's flattened variants
# (feature_inventory_auth / feature_inventory_tags).
_AUX_KICKOFF_KEYS = {
    "frontend": ("done_def", "feature_inventory", "reference_image_manifest", "task_tree"),
    "backend": ("done_def", "feature_inventory", "task_tree"),
    "verifier": ("done_def", "feature_inventory"),
}


def _is_aux_key(key: str, section: str) -> bool:
    return any(key == aux or key.startswith(aux)
               for aux in _AUX_KICKOFF_KEYS.get(section, ()))


def has_aux_content(content: Any, section: str) -> bool:
    """True if the decision ``content`` carries a NON-EMPTY auxiliary kickoff key
    (done_def / feature_inventory / reference_image_manifest / task_tree). These have
    NO dedicated kickoff_declare_* tool, so a section RECORDS them via
    workhub_add_meeting_decision. They are NOT buildable substance (don't advance the
    phase), but a decision carrying ONLY them must be ACCEPTED — the buildable
    ui_pages/endpoints/predicates arrive separately via the declare tools. Without this
    the tool hard-rejected an aux-only decision with 'no recognized key' (the 18×
    resend loop this module's design exists to prevent)."""
    if not isinstance(content, Mapping):
        return False
    for k, v in content.items():
        if k in _META_KEYS or not _is_aux_key(k, section):
            continue
        if isinstance(v, (list, tuple, Mapping)):
            if v:
                return True
        elif isinstance(v, str):
            if v.strip():
                return True
        elif v is not None:
            return True
    return False


def non_contract_keys(content: Any, section: str) -> list:
    """Return the sorted non-meta keys a decision carried that are NOT part of
    this section's kickoff contract — but ONLY when no recognized key is present
    at all.

    Distinguishes "the lane submitted the wrong thing" (e.g. ``{auth_model:
    'jwt'}`` — auth is framework-owned, not a section-contract field) from a
    truncated/empty payload of the right keys. youtube run #13: the backend
    re-submitted ``{auth_model: 'jwt'}`` 22× because the generic "no recognized
    content → SUBMIT IN PARTS" guidance implied truncation and told it to resend.
    Returns [] when ANY recognized key is present (then it's empty/partial, not
    wrong-keys) or when there is no real extra content."""
    if not isinstance(content, Mapping):
        return []
    recognized = set(_RECOGNIZED_KEYS.get(section, ()))
    present = {k for k in content if k not in _META_KEYS}
    if not present or (present & recognized):
        return []
    # A decision carrying ONLY legitimate auxiliary kickoff fields (done_def /
    # feature_inventory / ...) is the prompt-sanctioned "scalar fields" decision —
    # accept it (return []), don't reject it into a resend loop. Only keys that are
    # neither contract NOR aux (e.g. framework-owned auth / auth_model) are real
    # "wrong keys" — and the message then names exactly those.
    wrong = sorted(k for k in present if not _is_aux_key(k, section))
    return wrong


_AUTH_KEYS_1037 = ("auth", "auth_model", "authentication", "auth_scheme", "auth_strategy")


def near_miss_contract_keys_1037(wrong: Any, section: str) -> dict:
    """Map each wrong key to the contract key it is obviously reaching for.

    #1037: `non_contract_keys` names the wrong key, but the REMEDIATION beside it was
    hard-coded to the auth case it was written for (youtube run #13). Across the r1-r175
    corpus the actual distribution of rejected key-sets is:

        145  ['api_endpoints']      <- one key, 85% of all rejections
         10  auth / auth+notes / ... <- what the message actually talks about
         ~16 everything else

    So the guidance addressed 6% of the cases and misdirected the other 94%: a backend that
    sent `api_endpoints` was told, at length, not to declare auth — which it had not done.
    A wrong cause in an error message is the same defect as #1035's blank one and #1036's
    misnamed one; here it is simply the most repeated.

    Matching is deliberately conservative — a suffix/prefix relationship to a real contract
    key ("api_endpoints" -> "endpoints", "tables_declared" -> "tables"). Anything else gets
    no suggestion rather than a wrong one.
    """
    recognized = _RECOGNIZED_KEYS.get(section, ())
    out = {}
    for k in (wrong or []):
        kl = str(k).lower()
        for r in recognized:
            if kl == r:
                continue
            if kl.endswith("_" + r) or kl.startswith(r + "_"):
                out[str(k)] = r
                break
    return out


def wrong_keys_remediation_1037(wrong: Any, section: str, keys_hint: str, example: str) -> str:
    """The section-appropriate remediation for a wrong-keys decision.

    Says the auth sentence ONLY when an auth key is actually present, and names the
    near-miss substitution when there is one. See `near_miss_contract_keys_1037`.
    """
    wrong = list(wrong or [])
    parts = []
    near = near_miss_contract_keys_1037(wrong, section)
    if near:
        subs = ", ".join(f"`{k}` -> `{v}`" for k, v in sorted(near.items()))
        parts.append(
            f"You used a near-miss key name: {subs}. This section's contract key is spelled "
            f"exactly as shown on the right.")
    if any(str(k).lower() in _AUTH_KEYS_1037 for k in wrong):
        parts.append(
            "Auth is FRAMEWORK-OWNED (the generated stack embeds an OAuth2 AS minting JWTs) "
            "— do NOT declare auth_model/auth; the framework supplies it.")
    parts.append(
        f"Declare your real contract ({keys_hint}) via the dedicated kickoff_declare_* tools "
        f"(e.g. {example}). Do NOT re-submit this decision.")
    return " ".join(parts)


def _norm_ref_path(p: Any) -> str:
    """Normalize a reference-image path for comparison (strip, './', backslashes)."""
    return str(p or "").strip().replace("\\", "/").lstrip("./")


def manifest_paths(content: Any) -> list:
    """Reference-image paths a frontend section DECLARES — manifest dict keys, or items if a
    list/`{path:...}` form was submitted. [] when absent/empty (incl. the '{}' no-refs stub)."""
    if not isinstance(content, Mapping):
        return []
    m = content.get("reference_image_manifest")
    if isinstance(m, Mapping):
        return [_norm_ref_path(k) for k in m.keys() if str(k).strip()]
    if isinstance(m, (list, tuple)):
        out = []
        for it in m:
            if isinstance(it, str) and it.strip():
                out.append(_norm_ref_path(it))
            elif isinstance(it, Mapping) and it.get("path"):
                out.append(_norm_ref_path(it.get("path")))
        return out
    return []


def unviewed_manifest_paths(content: Any, viewed: Any) -> list:
    """§5: sorted manifest paths NOT in the agent's viewed-set. [] when nothing is declared,
    when no viewed-set is supplied (enforcement off — e.g. the facilitator has no handle), or
    when the manifest is the explicit '{}' no-references stub. PURE — unit-testable."""
    declared = manifest_paths(content)
    if not declared or viewed is None:
        return []
    seen = {_norm_ref_path(v) for v in viewed}
    return sorted(p for p in declared if p not in seen)


def real_items(seq: Any) -> int:
    """Count NON-EMPTY items — mappings OR non-empty strings.

    Null-placeholder skeletons ([null, ...]), empty mappings and blank strings
    count 0 (the malformed/empty shells this guard exists to reject). Plain
    strings count because a section legitimately submits list-of-strings content
    — e.g. the verifier's predicates as descriptions
    (['docker_up succeeds', 'validation:api_smoke passes']) — which previously
    read as 0 and was falsely rejected as "no substantive content"."""
    if not isinstance(seq, (list, tuple)):
        return 0
    return sum(1 for x in seq
               if (isinstance(x, Mapping) and x) or (isinstance(x, str) and x.strip()))


def section_has_substance(content: Any, section: str) -> bool:
    if not isinstance(content, Mapping):
        return False
    if content.get("deferred"):
        return False
    if section == "frontend":
        # ALL first-class frontend declarations count as substance — each has a
        # dedicated kickoff_declare_* tool and the section MERGES parts. Counting
        # only ui_pages/screens wrongly rejected a `user_flows`-only part submitted
        # via the generic workhub_add_meeting_decision tool (kickoff_declare_user_flow
        # bypasses this guard by calling the service directly), even though that IS
        # the "submit in parts" the guard's own error message demands. Empty shells
        # / null skeletons still read as no-substance (real_items() counts only
        # non-empty mappings).
        return bool(real_items(content.get("ui_pages"))
                    or real_items(content.get("screens"))
                    or real_items(content.get("user_flows"))
                    or real_items(content.get("ui_components")))
    if section == "backend":
        dm = content.get("data_model")
        return bool(real_items(content.get("endpoints"))
                    or (isinstance(dm, Mapping) and real_items(dm.get("tables"))))
    if section == "verifier":
        return bool(real_items(content.get("predicates")))
    return True


def decision_has_substance(decision: Any, section: str) -> bool:
    """Both decision shapes: {"section","content":{...}} and flat."""
    if not isinstance(decision, Mapping):
        return False
    if section_has_substance(decision.get("content"), section):
        return True
    flat = {k: v for k, v in decision.items() if k not in _META_KEYS}
    return section_has_substance(flat, section)


def decision_advances_phase(decision: Any, section: str) -> bool:
    """May this decision advance the kickoff phase for its section?
    YES for substantive content, YES for an explicit deferred stub (the
    terminal advance-anyway marker after corrective turns are exhausted),
    NO for empty shells / null skeletons (the author is still being
    corrected — the meeting must wait)."""
    if not isinstance(decision, Mapping):
        return False
    content = decision.get("content")
    if isinstance(content, Mapping) and content.get("deferred"):
        return True
    if decision.get("deferred"):
        return True
    return decision_has_substance(decision, section)
