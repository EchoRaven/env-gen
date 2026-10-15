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
    # --- #1203m1 ----------------------------------------------------------------------
    # The abort advice must name the limit that actually bound, and a cause that already
    # names its own ENVGEN_* knob must get no second opinion appended.
    _ab = re.findall(
        r"Run budget exceeded \((.*?)\) without delivery; aborted after \d+ "
        r"coordination ticks\.([^\n\x1b]*)", logtext, re.S)
    if not _ab:
        say("m1", "N-A", "this run did not hit a budget abort")
    else:
        _cause, _adv = _ab[-1]
        _adv = _adv.strip()
        if "ENVGEN_MAX_" in _cause:
            say("m1", "CONFIRMED" if not _adv else "FALSIFIED",
                "self-explaining cause, trailing advice=%r" % _adv)
        elif _cause.startswith("wall-clock"):
            ok = _adv == "Adjust via ENVGEN_MAX_WALLCLOCK_SEC."
            say("m1", "CONFIRMED" if ok else "FALSIFIED", "wall-clock cause, advice=%r" % _adv)
        elif _cause.startswith("coordination ticks"):
            ok = _adv == "Adjust via ENVGEN_MAX_TICKS."
            say("m1", "CONFIRMED" if ok else "FALSIFIED", "tick cause, advice=%r" % _adv)
        else:
            say("m1", "INFO", "cause shape not in the corpus: %s" % _cause[:60])

    # --- #1203m2 ----------------------------------------------------------------------
    # The Playwright driver should not reach its heap ceiling. If it still does, the number
    # beside the fatal line says whether the raised ceiling took effect (~8100 MB, leak still
    # wins) or was never applied (~4100 MB, the patch did not reach this spawn).
    _ooms = list(re.finditer(r"JavaScript heap out of memory", logtext))
    _drv = len(re.findall(r"Connection closed while reading from the driver", logtext))
    _rel = len(re.findall(r"#1198 shared browser driver is gone \(relaunch", logtext))
    if not _ooms:
        say("m2", "CONFIRMED", "no driver OOM; driver-closed=%d relaunches=%d" % (_drv, _rel))
    else:
        _peaks = []
        for _m in _ooms:
            _seg = logtext[max(0, _m.start() - 2500):_m.start()]
            _mb = [float(x) for x in re.findall(r"(\d{3,5}\.\d) \(\d", _seg)]
            if _mb:
                _peaks.append(max(_mb))
        _hi = max(_peaks) if _peaks else 0.0
        if _hi >= 7000:
            say("m2", "CONFIRMED",
                "ceiling applied (peak %.0f MB) but the leak still reached it: %d OOM, "
                "driver-closed=%d relaunches=%d" % (_hi, len(_ooms), _drv, _rel))
        else:
            say("m2", "FALSIFIED",
                "OOM at %.0f MB -- the raised ceiling did not reach this spawn (%d OOM)"
                % (_hi, len(_ooms)))

    # --- #1203m3 ----------------------------------------------------------------------
    # If the seeded-media P1 is filed and any listed path is remapped by the page, the task
    # must say so; if none is remapped, the caveat must be absent.
    _tasks = _json(run / "shared" / "hubs" / "workhub_tasks.json", {}) or {}
    def _w(o):
        if isinstance(o, dict):
            yield o
            for v in o.values():
                yield from _w(v)
        elif isinstance(o, list):
            for v in o:
                yield from _w(v)
    _seed_tasks = [o for o in _w(_tasks)
                   if str(o.get("title") or "").startswith("Seeded media missing at delivery")]
    if not _seed_tasks:
        say("m3", "N-A", "the seeded-media task was not filed in this run")
    else:
        _d = " ".join(str(o.get("description") or "") for o in _seed_tasks)
        _pub = run / "app" / "frontend" / "public"
        _listed = re.findall(r"  - (/assets/\S+)", _d)
        _absent = [u for u in _listed if not (_pub / u.lstrip("/")).exists()]
        _src = run / "app" / "frontend" / "src"
        _txt = ""
        if _src.is_dir():
            for _f in list(_src.rglob("*.js")) + list(_src.rglob("*.jsx")):
                _txt += _f.read_text(encoding="utf-8", errors="replace")
        _rm = [u for u in _absent
               if re.search(re.escape("'" + u + "'") + r"\s*:", _txt)
               or re.search(re.escape('"' + u + '"') + r"\s*:", _txt)]
        if _rm:
            say("m3", "CONFIRMED" if "#1203m3" in _d else "FALSIFIED",
                "%d of %d listed paths are remapped by the page; caveat present=%s"
                % (len(_rm), len(_listed), "#1203m3" in _d))
        else:
            say("m3", "CONFIRMED" if "#1203m3" not in _d else "FALSIFIED",
                "no listed path is remapped; caveat absent=%s" % ("#1203m3" not in _d))

    # --- #1203m4 ----------------------------------------------------------------------
    # No probe may be scored `fail` for a 400/422 whose body names a field it never sent.
    _runs = _json(run / "shared" / "hubs" / "runhub_runs.json", {}) or {}
    _need = re.compile(r"\brequired\b|\"type\"\s*:\s*\"missing\"|\bmissing\b"
                       r"|cannot be empty|must not be empty", re.I)
    _bad4, _n4 = [], 0
    for _r in _w(_runs):
        if not (isinstance(_r, dict) and "verdict" in _r and "status_code" in _r):
            continue
        _n4 += 1
        if str(_r.get("verdict") or "").lower() not in ("fail", "failed"):
            continue
        if _r.get("status_code") in (400, 422) and _need.search(str(_r.get("body_excerpt") or "")):
            _bad4.append("%s %s" % (_r.get("method"), _r.get("path")))
    if not _n4:
        say("m4", "N-A", "no probe records in this run")
    else:
        say("m4", "FALSIFIED" if _bad4 else "CONFIRMED",
            "%d probe record(s); scored-fail-on-own-empty-request: %d %s"
            % (_n4, len(_bad4), sorted(set(_bad4))[:3]))

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
