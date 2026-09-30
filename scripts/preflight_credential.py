"""Does the configured LLM credential actually ANSWER? One HTTP call, before a run starts.

r141 cleared all six of `tiktok_designinput.sh`'s preflights — provider/model set, key
present, no concurrent run, design materials staged, 60G free, playwright installed — and
then died 82.7 s in (612 s of process wall clock) on
`429 insufficient_quota: You have no credits remaining`. The launcher checks that the key
EXISTS; nothing checked that it WORKS. This does, in about two seconds.

Exit codes, and the distinction is the whole design:

    0  the credential answered (or the provider is one we cannot probe) -> start the run
    1  a DEFINITIVE refusal -- 401/403, or 429 whose body names a quota/billing condition.
       The run cannot make progress; the launcher refuses.
    2  INCONCLUSIVE -- timeout, DNS, connection reset, 5xx, an unparseable body. NOT a
       refusal: a network blip must not block a launch, and the run's own retry logic is
       built for exactly that. Refusing here would trade a wasted run for a false one.

A plain 429 WITHOUT a quota phrase is inconclusive too, because that is ordinary throttling
and it clears on its own -- #1159 and #1174 paid for that distinction twice (r15 spent 2h50m
retrying a dead account; r16 was killed by a 57-second blip on a live one).

    python scripts/preflight_credential.py          # after sourcing the key file
    ENVGEN_PREFLIGHT=0 ...                          # skip it entirely
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

_QUOTA = ("insufficient_quota", "credit_balance_exhausted", "no credits remaining",
          "billing", "exceeded your current quota", "payment")
_SCRUB = re.compile(r"(sk-|key-)[A-Za-z0-9_\-]{6,}")


def _scrub(text: str) -> str:
    return _SCRUB.sub(r"\1***", str(text))[:300]


def probe(timeout: float = 40.0):
    """(exit_code, message). Never raises, never prints the key."""
    provider = (os.environ.get("ENVGEN_PROVIDER") or "openai").strip().lower()
    key = (os.environ.get("ENVGEN_LLM_KEY")
           or os.environ.get("OPENAI_API_KEY")
           or os.environ.get("ANTHROPIC_API_KEY") or "")
    model = (os.environ.get("ENVGEN_MODEL") or "").strip()
    if provider not in ("openai", "anthropic"):
        return 0, ("provider %r is not probeable here; the launcher's own key check stands"
                   % provider)
    if not key or not model:
        return 2, "no ENVGEN_LLM_KEY/ENVGEN_MODEL in the environment — nothing to probe"
    base = (os.environ.get("ENVGEN_API_BASE")
            or ("https://api.anthropic.com/v1" if provider == "anthropic"
                else "https://api.openai.com/v1")).rstrip("/")
    if provider == "anthropic":
        url, headers = base + "/messages", {
            "x-api-key": key, "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"}
    else:
        url, headers = base + "/chat/completions", {
            "Authorization": "Bearer " + key, "Content-Type": "application/json"}
    body = {"model": model, "max_tokens": 1,
            "messages": [{"role": "user", "content": "ok"}]}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 0, "the credential answers (HTTP %s, model %s)" % (resp.status, model)
    except urllib.error.HTTPError as exc:
        try:
            text = exc.read().decode("utf-8", "replace")
        except Exception:
            text = ""
        low = text.lower()
        if exc.code in (401, 403):
            return 1, "HTTP %s — the credential is rejected: %s" % (exc.code, _scrub(text))
        if exc.code == 429 and any(p in low for p in _QUOTA):
            return 1, ("HTTP 429 with a billing condition — the account cannot make "
                       "progress: %s" % _scrub(text))
        if exc.code == 429:
            return 2, ("HTTP 429 without a billing phrase — ordinary throttling, which "
                       "clears on its own (#1174): %s" % _scrub(text))
        if exc.code == 404:
            return 1, ("HTTP 404 — the endpoint or model %r does not exist at %s; a run "
                       "would fail on its first call: %s" % (model, base, _scrub(text)))
        return 2, "HTTP %s — inconclusive: %s" % (exc.code, _scrub(text))
    except Exception as exc:
        return 2, "%s: %s — inconclusive, not a refusal" % (type(exc).__name__, _scrub(exc))


def main():
    if (os.environ.get("ENVGEN_PREFLIGHT", "1").strip().lower()
            in ("0", "false", "off", "no")):
        print("[preflight] skipped (ENVGEN_PREFLIGHT=0)")
        return 0
    code, msg = probe()
    tag = {0: "[preflight] OK", 1: "[preflight] REFUSED", 2: "[preflight] WARN"}[code]
    print("%s %s" % (tag, msg))
    if code == 1:
        print("[preflight] Not starting a run against a credential that cannot answer. "
              "r141 spent 612 s of wall clock learning this the other way.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
