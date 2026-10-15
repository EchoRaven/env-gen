#!/usr/bin/env python3
"""Check a run directory against the 2026-10-15 tickets' PRE-REGISTERED predictions.

    python scripts/verify_1015.py generated/<run>            # one run
    python scripts/verify_1015.py generated/<run> --log gm_x.log

Every line prints CONFIRMED / FALSIFIED / N-A with the number it read, so a result cannot be
re-interpreted afterwards. The predictions are the ones written down before the run
(memory: project_envgen_r189_preregistered_2026_10_15); this file is only their executable form.

VALIDATED ON A KNOWN ANSWER, which is the point of running it before it is needed: against
`generated/tiktok-web-r185` -- a run that predates every one of these patches -- it reports

    6 falsified, 5 confirmed, 2 not applicable

and the six are exactly the pre-patch state (both empty sprite hosts staged, 0 of 22 assets
carrying `type`, no component crops, no layout_metrics, no dataset manifest, and all four
#1202lz lines naming the gate's own probe). A checker that reported everything CONFIRMED on an
old run would be measuring nothing. The five CONFIRMED there are product-dependent checks that
r185 happened to pass anyway -- tiktok's scraped icons already carry xmlns, its pool has no
avatar, its shared nav mounted, and it emitted one COMPONENT DRIFT line.
"""
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SVG_TAG = "{http://www.w3.org/2000/svg}svg"
PROBE = ("/api/profiles", "/api/profile", "/profiles")
OUT = []


def say(ticket, verdict, detail):
    OUT.append((ticket, verdict, detail))


def _json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return default


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    run = Path(argv[1])
    log = None
    if "--log" in argv:
        log = Path(argv[argv.index("--log") + 1])
    logtext = ""
    if log and log.is_file():
        logtext = log.read_text(encoding="utf-8", errors="replace")

    icons = run / "app" / "frontend" / "public" / "assets" / "icons"
    pub = run / "app" / "frontend" / "public" / "assets"
    ds = _json(run / "design" / "design_system.json", {}) or {}
    verdict = _json(run / "design" / "visual_gate" / "verdict.json", {}) or {}
    screens = verdict.get("screens") or []
    if isinstance(screens, dict):
        screens = list(screens.values())

    # --- #1203ku -----------------------------------------------------------------------
    sprites = [n for n in ("icon_0065272a.svg", "icon_732aaf84.svg")
               if (icons / n).is_file()]
    say("ku", "FALSIFIED" if sprites else "CONFIRMED",
        "empty sprite hosts staged: %s" % (sprites or "none"))

    # --- #1203l6 -----------------------------------------------------------------------
    bad = []
    for f in pub.rglob("*.svg") if pub.is_dir() else []:
        try:
            if ET.fromstring(f.read_text(encoding="utf-8", errors="replace")).tag != SVG_TAG:
                bad.append(f.name)
        except Exception:
            bad.append(f.name + " (unparseable)")
    say("l6", "FALSIFIED" if bad else "CONFIRMED",
        "%d staged svg(s) an <img> cannot decode: %s" % (len(bad), bad[:3] or "none"))

    broken = logtext.lower().count("broken image") + logtext.lower().count("broken-image")
    say("l6-effect", "CONFIRMED" if broken == 0 else "FALSIFIED",
        "'broken image' mentions in the log: %d" % broken)

    # --- #1203kv -----------------------------------------------------------------------
    assets = [a for a in (ds.get("assets") or []) if isinstance(a, dict)]
    KNOWN = (".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".woff2", ".woff")
    want = [a for a in assets if Path(str(a.get("file") or "")).suffix.lower() in KNOWN]
    typed = [a for a in want if str(a.get("type") or "").strip()]
    say("kv", "CONFIRMED" if want and len(typed) == len(want) else
        ("N-A" if not want else "FALSIFIED"),
        "assets with a known suffix carrying `type`: %d/%d" % (len(typed), len(want)))

    # --- #1203kx -----------------------------------------------------------------------
    pool = [a for a in assets
            if str(a.get("type") or "").lower() in ("jpg", "jpeg", "png", "webp")
            and "avatar" in (str(a.get("id")) + str(a.get("file"))).lower()]
    say("kx", "CONFIRMED" if not pool else "FALSIFIED",
        "avatar assets that would enter the poster pool: %d" % len(pool))

    # --- #1203ky -----------------------------------------------------------------------
    crops = list((run / "design" / "crops").glob("*.png")) if (
        run / "design" / "crops").is_dir() else []
    say("ky", "CONFIRMED" if crops else "FALSIFIED", "component crops on disk: %d" % len(crops))

    # --- #1203kz -----------------------------------------------------------------------
    m = re.search(r"(\d+) carrying verbatim copy", logtext)
    if not m:
        say("kz", "N-A", "the completion-pass line is not in the log provided")
    else:
        say("kz", "CONFIRMED" if int(m.group(1)) > 0 else "FALSIFIED",
            "components carrying verbatim copy: %s" % m.group(1))

    # --- #1203l0 -----------------------------------------------------------------------
    lm = [s for s in (ds.get("screens") or []) if isinstance(s, dict) and s.get("layout_metrics")]
    say("l0-layout", "CONFIRMED" if lm else "FALSIFIED",
        "screens carrying layout_metrics: %d/%d" % (len(lm), len(ds.get("screens") or [])))
    say("l0-dataset",
        "CONFIRMED" if (ds.get("dataset") or []) else
        ("N-A" if not (run / "design" / "dataset").is_dir() else "FALSIFIED"),
        "dataset manifest entries: %d" % len(ds.get("dataset") or []))

    # --- #1203l2 -----------------------------------------------------------------------
    if "#576 mounted shared nav" in logtext:
        say("l2", "CONFIRMED", "the shared nav was mounted")
    elif "did not mount a shared nav" in logtext:
        say("l2", "FALSIFIED", "refused: %s" % re.search(
            r"did not mount a shared nav: ([^\n]{0,60})", logtext).group(1))
    else:
        say("l2", "N-A", "no #576 line — this run may have no dominant shell")

    # --- #1203l4 -----------------------------------------------------------------------
    drift = len(re.findall(r"COMPONENT DRIFT", logtext))
    say("l4", "CONFIRMED" if drift <= 2 else "FALSIFIED",
        "COMPONENT DRIFT lines: %d (corpus baseline was ~46%% of pages)" % drift)

    # --- #1203l7 -----------------------------------------------------------------------
    lz = re.findall(r"1202lz the browser called [^\n]{0,400}", logtext)
    probed = [x for x in lz if any(p in x for p in PROBE)]
    say("l7", "CONFIRMED" if not probed else "FALSIFIED",
        "#1202lz lines naming the gate's own probe: %d of %d" % (len(probed), len(lz)))

    # --- #1203l8 -----------------------------------------------------------------------
    api = {k: v for k, v in (verdict.get("api_404s_1202lz") or {}).items() if k not in PROBE}
    named = 0
    for path, names in api.items():
        for n in (names or []):
            for s in screens:
                if str(s.get("name")) == str(n) and path in str(s.get("deviations") or ""):
                    named += 1
    total = sum(len(v or []) for v in api.values())
    say("l8", "N-A" if total == 0 else ("CONFIRMED" if named == total else "FALSIFIED"),
        "per-screen 404s named in their own deviation: %d/%d" % (named, total))

    # --- the two older things to look at ------------------------------------------------
    hold = run / "logs" / "delivery_hold.jsonl"
    last = None
    if hold.is_file():
        for ln in hold.read_text(encoding="utf-8", errors="replace").split("\n"):
            if ln.strip():
                try:
                    last = json.loads(ln)
                except Exception:
                    pass
    say("final-hold", "INFO", (last or {}).get("detail") or "no hold record")

    w = max(len(t) for t, _, _ in OUT)
    for t, v, d in OUT:
        print(f"  {t:<{w}}  {v:<10} {d}")
    bad_n = sum(1 for _, v, _ in OUT if v == "FALSIFIED")
    print("\n%d falsified, %d confirmed, %d not applicable" % (
        bad_n, sum(1 for _, v, _ in OUT if v == "CONFIRMED"),
        sum(1 for _, v, _ in OUT if v == "N-A")))
    return 1 if bad_n else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
