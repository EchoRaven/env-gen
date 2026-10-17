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
import pathlib
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

    # #1203ms: THIS CRITERION WAS WRONG TWICE, and the second fix was the same mistake as
    # the first. It counted "broken image" over the whole log; #1203mp sliced that to the
    # last staging pass. But the phrase comes from `#1203g9`, which fires at DELIVERY-GATE
    # time -- after staging -- so the slice window never covered it. r190: #1203g9 named six
    # invented video filenames at 07:19 (`dance_rooftop.mp4` beside the real
    # `charlidamelio__7661492762902023437.mp4`), the lane replaced them with real ones, and
    # the DELIVERED tree has zero missing. The framework was right and the criterion was not.
    #
    # So it stops reading the log. The question -- does a referenced asset exist? -- is
    # answerable on the artifact, which is also the only form immune to a verdict the run
    # later retracted. Same scope as `#1203g9` itself: quoted literal `/assets/...` paths in
    # frontend/src, checked against public/.
    _fe_ms = run / "app" / "frontend"
    _refs_ms, _miss_ms = set(), []
    if (_fe_ms / "src").is_dir() and (_fe_ms / "public").is_dir():
        for _f in sorted((_fe_ms / "src").rglob("*")):
            if _f.suffix.lower() not in (".jsx", ".js", ".tsx", ".ts", ".css", ".html"):
                continue
            if "node_modules" in _f.parts:
                continue
            try:
                _t = _f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for _r in re.findall(
                    r"""['"`](/(?:assets|images|img|icons|static|media|fonts)/"""
                    r"""[A-Za-z0-9_./@-]+)['"`]""", _t):
                _refs_ms.add(_r)
        _miss_ms = [r for r in sorted(_refs_ms)
                    if not (_fe_ms / "public" / r.lstrip("/")).exists()]
    if not _refs_ms:
        say("l6-effect", "N-A", "no frontend src/public pair to check")
    else:
        say("l6-effect", "CONFIRMED" if not _miss_ms else "FALSIFIED",
            "%d literal asset ref(s) in the DELIVERED tree; missing under public/: %d %s"
            % (len(_refs_ms), len(_miss_ms), _miss_ms[:3]))

    # --- #1203kv -----------------------------------------------------------------------
    assets = [a for a in (ds.get("assets") or []) if isinstance(a, dict)]
    KNOWN = (".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".woff2", ".woff")
    want = [a for a in assets if Path(str(a.get("file") or "")).suffix.lower() in KNOWN]
    typed = [a for a in want if str(a.get("type") or "").strip()]
    say("kv", "CONFIRMED" if want and len(typed) == len(want) else
        ("N-A" if not want else "FALSIFIED"),
        "assets with a known suffix carrying `type`: %d/%d" % (len(typed), len(want)))

    # --- #1203kx -----------------------------------------------------------------------
    # #1203mj: this re-implemented the filter by hand -- `"avatar" in id+file` over the
    # staged assets -- and reported r189 FALSIFIED on 4 real avatars. That was MY criterion
    # being wrong twice over. It asked whether avatars are STAGED (they must be; they are
    # avatars) instead of whether they enter the POSTER POOL, and it answered with its own
    # copy of a rule the framework owns -- #772's trap, where a hand-written re-implementation
    # disagrees with the shipped one and the disagreement reads as a finding. The shipped
    # `_ref_image_pool` on that same run returns an EMPTY pool: the fix works.
    try:
        import sys as _sys_kx
        _sys_kx.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "agent"))
        from env_generator.llm_generator.multi_agent.runtime import frontend_scaffold as _FS_kx
        _pool_kx = _FS_kx._ref_image_pool(ds)
        _av_kx = [p for p in _pool_kx if "avatar" in str(p).lower()]
        say("kx", "CONFIRMED" if not _av_kx else "FALSIFIED",
            "shipped _ref_image_pool: %d entr(ies), avatars among them: %d %s"
            % (len(_pool_kx), len(_av_kx), _av_kx[:3]))
    except Exception as _e_kx:
        say("kx", "N-A", "could not import the shipped pool builder: %s" % _e_kx)

    # --- #1203ky -----------------------------------------------------------------------
    crops = list((run / "design" / "crops").glob("*.png")) if (
        run / "design" / "crops").is_dir() else []
    say("ky", "CONFIRMED" if crops else "FALSIFIED", "component crops on disk: %d" % len(crops))

    # --- #1203kz -----------------------------------------------------------------------
    # #1203mp: this took re.SEARCH -- the FIRST completion pass in the log -- and design-prep
    # can run several, with the early ones naturally at 0 before the analyst has written
    # anything. A criterion that reads the first pass judges a run on its opening state. Ask
    # the DELIVERED document first (the thing the claim is actually about) and fall back to
    # the LAST log line, never the first.
    _comps_kz = []
    for _sc_kz in (ds.get("screens") or []):
        if isinstance(_sc_kz, dict):
            _comps_kz.extend(c for c in (_sc_kz.get("components") or [])
                             if isinstance(c, dict))
    _comps_kz.extend(c for c in (ds.get("components") or []) if isinstance(c, dict))
    if _comps_kz:
        _withcopy_kz = [c for c in _comps_kz
                        if isinstance(c.get("copy"), str) and c["copy"].strip()]
        say("kz", "CONFIRMED" if _withcopy_kz else "FALSIFIED",
            "components in the DELIVERED design_system.json carrying verbatim copy: %d/%d"
            % (len(_withcopy_kz), len(_comps_kz)))
    elif not re.findall(r"(\d+) carrying verbatim copy", logtext):
        say("kz", "N-A", "no delivered components and no completion-pass line")
    else:
        m = re.match(r"(\d+)", re.findall(r"(\d+) carrying verbatim copy", logtext)[-1])
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
    # #1203mj: counting this over the WHOLE log counts verdicts that were TRUE when emitted.
    # r189's four COMPONENT DRIFT lines all landed at 14:13:40; the component they say is
    # unrendered (`ForYouExperience`, which renders TikTokShell/VideoPlayer/ActionRail) was
    # written at 15:02:52, 49 minutes later, and the run ended at 15:15:44. Run the SHIPPED
    # walker over the DELIVERED tree and all four pages come back with nothing missing.
    #
    # This is the same mistake I had diagnosed in #1203fh hours earlier -- its false branch
    # also fires only before the lane writes the file -- and then repeated here. A log-line
    # count is a claim about the whole run; a claim about the app has to be made against the
    # app. The line count is kept as INFO because it still says how noisy the pass was.
    drift = len(re.findall(r"COMPONENT DRIFT", logtext))
    say("l4-log", "INFO",
        "COMPONENT DRIFT lines: %d (corpus baseline was ~46%% of pages)" % drift)
    try:
        import sys as _sys_l4
        _sys_l4.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "agent"))
        from env_generator.llm_generator.multi_agent.runtime import frontend_audit as _FA_l4
        _fe_l4 = run / "app" / "frontend"
        _src_l4 = _fe_l4 / "src"
        _pages_l4 = _json(run / "shared" / "hubs" / "registryhub_ui_pages.json", {}) or {}
        _cache_l4 = {str(f): f.read_text(encoding="utf-8", errors="ignore")
                     for f in _fe_l4.rglob("*.jsx")} if _fe_l4.is_dir() else {}
        _bad_l4 = []
        for _k, _v in _pages_l4.items():
            if _k == "_meta" or not isinstance(_v, dict):
                continue
            _want = {_FA_l4._norm_component_1203l4(c) for c in (_v.get("components") or [])}
            if not _want:
                continue
            _got = _FA_l4._rendered_components_909(_src_l4, _v, _cache_l4)
            _missing = _want - {_FA_l4._norm_component_1203l4(g) for g in _got}
            if _missing == _want:
                _bad_l4.append("%s(%s)" % (_v.get("name"), ",".join(sorted(_missing))[:40]))
        # What this can decide mechanically is the RATE, not the truth of each verdict.
        # #1203l4 removed a false class (110 -> 12 corpus-wide, 46% -> ~5% of pages); it did
        # not promise zero, and a surviving verdict may be correct. r189's one survivor IS:
        # `messages_dm_empty_page` declares `BrowseShell` and hand-rolls its own nav rail
        # inline instead, while ProfileOwnPage and LiveDiscoverPage both import it. So the
        # pass condition is the rate collapsing, with the names printed for adjudication --
        # a criterion that fails on a true positive is measuring the wrong thing.
        _tot_l4 = sum(1 for _k, _v in _pages_l4.items()
                      if _k != "_meta" and isinstance(_v, dict) and (_v.get("components") or []))
        _rate_l4 = (len(_bad_l4) / _tot_l4) if _tot_l4 else 0.0
        say("l4", "CONFIRMED" if _rate_l4 <= 0.20 else "FALSIFIED",
            "pages rendering NONE of their declared components ON THE DELIVERED TREE: "
            "%d/%d = %.0f%% (corpus baseline 46%%, post-fix ~5%%) %s"
            % (len(_bad_l4), _tot_l4, _rate_l4 * 100, _bad_l4[:3]))
    except Exception as _e_l4:
        say("l4", "N-A", "could not run the shipped walker: %s" % _e_l4)

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

    # --- #1203m5 ----------------------------------------------------------------------
    # Every "type changed" breaking-change P0 must name the pair, not just the field.
    _bc = [o for o in _w(_tasks)
           if str(o.get("title") or "").startswith("Fix breaking change")
           and "type changed" in str(o.get("title") or "")]
    if not _bc:
        say("m5", "N-A", "no type-change breaking P0 was filed in this run")
    else:
        _mute = [str(o.get("title"))[:48] for o in _bc
                 if " -> " not in str(o.get("description") or "")]
        say("m5", "FALSIFIED" if _mute else "CONFIRMED",
            "%d type-change P0(s); without the pair: %d %s"
            % (len(_bc), len(_mute), _mute[:2]))

    # --- #1203m6 / #1203m7 / #1203m8 --------------------------------------------------
    _bcs = _json(run / "shared" / "hubs" / "registryhub_breaking_changes.json", {}) or {}
    _eps = _json(run / "shared" / "hubs" / "registryhub_endpoints.json", {}) or {}
    _per = {}
    for _k, _v in _bcs.items():
        if _k == "_meta" or not isinstance(_v, dict):
            continue
        _per.setdefault(_v.get("endpoint_id"), []).append(_v)
    for _e in _per:
        _per[_e].sort(key=lambda r: r.get("created_at") or 0)

    # m6: a response-key change must name both keys in the TITLE.
    _rk = [o for o in _w(_tasks)
           if str(o.get("title") or "").startswith("Fix breaking change")
           and "response key" in str(o.get("title") or "")]
    _bare = [o for o in _w(_tasks)
             if str(o.get("title") or "").startswith("Fix breaking change")
             and ":" not in str(o.get("title") or "")[len("Fix breaking change in "):]]
    if not _per:
        say("m6", "N-A", "no breaking-change record in this run")
    else:
        say("m6", "FALSIFIED" if _bare else "CONFIRMED",
            "%d response-key title(s); titles with NO detail at all: %d (corpus baseline 114/441)"
            % (len(_rk), len(_bare)))

    # m7: how many endpoints declare the key in the schema only -- the population the
    # effective-key read serves. Reported, not judged: one run cannot falsify it.
    _schema_only = 0
    for _k, _v in _eps.items():
        if _k == "_meta" or not isinstance(_v, dict):
            continue
        _sc = _v.get("schema") if isinstance(_v.get("schema"), dict) else {}
        _md = _v.get("metadata") if isinstance(_v.get("metadata"), dict) else {}
        if _sc.get("response_key") and not _md.get("response_key"):
            _schema_only += 1
    say("m7", "INFO", "endpoints declaring response_key in the SCHEMA only: %d" % _schema_only)

    # m8: a first registration must not mint a record. Measured as the share of endpoints
    # whose EARLIEST record uses only the two flags an absent `old` can set -- 93% (888/955)
    # before the fix.
    _FIRSTABLE = {"response_key_changed", "auth_added"}
    _only = 0
    for _e, _recs in _per.items():
        _b = _recs[0].get("breaking") or {}
        _on = {f for f, v in _b.items()
               if f != "is_breaking" and (v is True or (isinstance(v, list) and v))}
        if _on and _on <= _FIRSTABLE:
            _only += 1
    if not _per:
        say("m8", "N-A", "no breaking-change record in this run")
    else:
        _share = 100.0 * _only / len(_per)
        say("m8",
            "FALSIFIED" if _share >= 80 else ("CONFIRMED" if _share < 50 else "INFO"),
            "%d/%d endpoints (%.0f%%) have a first-registration-shaped earliest record "
            "(baseline 93%%)" % (_only, len(_per), _share))

    # --- #1203m9 ----------------------------------------------------------------------
    # No kickoff document may hand a lane an Express-style API path. The pattern is a colon
    # right after a SLASH -- `{id:int}` is a legal FastAPI converter and must not match (my
    # first detector called r167's legal path a violation).
    _exp = re.compile(r"`[A-Z]+ (/[^`]*/:[A-Za-z_][A-Za-z0-9_]*[^`]*)`")
    _docs = list((run / "docs").rglob("*.md")) if (run / "docs").is_dir() else []
    _bad9 = []
    for _f in _docs:
        try:
            for _m9 in _exp.findall(_f.read_text(encoding="utf-8", errors="replace")):
                _bad9.append("%s: %s" % (_f.name, _m9))
        except Exception:
            continue
    if not _docs:
        say("m9", "N-A", "no kickoff documents in this run")
    else:
        say("m9", "FALSIFIED" if _bad9 else "CONFIRMED",
            "%d kickoff doc(s); Express-style API paths: %d %s"
            % (len(_docs), len(_bad9), sorted(set(_bad9))[:2]))

    # --- #1203mb -----------------------------------------------------------------------
    # The table detector is dormant (`update_table_schema`: 0 calls in 172 runs), so a run
    # cannot falsify the fix directly. Two things are worth reporting: whether anything has
    # STARTED recording table breaking changes, and how much churn the run's own
    # `table_registered` events carry -- that is the population the fix de-noises.
    _tbc = _json(run / "shared" / "hubs" / "registryhub_table_breaking_changes.json", {}) or {}
    _tbc_n = len([k for k in _tbc if k != "_meta"])
    _evs = _json(run / "shared" / "hubs" / "eventhub_events.json", {}) or {}
    _hist: dict = {}
    for _o in _w(_evs):
        if str(_o.get("event_type") or "") != "table_registered":
            continue
        _pl = _o.get("payload") or {}
        if not (isinstance(_pl, dict) and _pl.get("name")):
            continue
        _sc = _pl.get("schema")
        if not (isinstance(_sc, dict) and isinstance(_sc.get("columns"), list)):
            continue
        _cols = {str(c.get("name")): str(c.get("type") or "")
                 for c in _sc["columns"] if isinstance(c, dict) and c.get("name")}
        _hist.setdefault(str(_pl["name"]), []).append((_o.get("created_at") or 0, _cols))
    _rawdiff = _gone = 0
    for _n2, _seq in _hist.items():
        _seq.sort(key=lambda x: x[0])
        for (_t0, _a), (_t1, _b) in zip(_seq, _seq[1:]):
            _gone += len(set(_a) - set(_b))
            _rawdiff += sum(1 for _c in set(_a) & set(_b) if _a[_c] != _b[_c])
    if not _hist:
        say("mb", "N-A", "no table_registered events in this run")
    else:
        say("mb", "INFO",
            "%d table histories; raw declared-type differences %d, column removals %d; "
            "table_breaking_changes records %d (corpus: 1712 raw -> 1061 real, 341 removals, "
            "0 records in 227 runs)" % (len(_hist), _rawdiff, _gone, _tbc_n))

    # --- #1203md / #1203me / #1203mf / #1203mg ------------------------------------------
    # The delivered BACKEND must contain no name nothing binds. Four defects of exactly that
    # shape were fixed on 2026-10-15 -- an unbound `_sys` in the seed-shortfall report
    # (110/110 files), a `user` a projected handler never took (r156/r160/r166), a bare
    # `text(` in #803's label read (17/17 of the files that have one), and unreachable
    # statements after an action stub that read an unbound `valid` (72). Every one sat on an
    # error or degradation path, so nothing crashed loudly and no test walked it.
    _be = run / "app" / "backend"
    if not _be.is_dir():
        say("names", "N-A", "this run has no delivered backend")
    else:
        try:
            import importlib.util as _ilu
            _spec = _ilu.spec_from_file_location(
                "_undef_1015", str(pathlib.Path(__file__).resolve().parent
                                   / "undefined_names.py"))
            _mod = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
        except Exception as _e:
            say("names", "N-A", "undefined_names.py unavailable: %s" % _e)
        else:
            _files = [p2 for p2 in _be.rglob("*.py") if "__pycache__" not in str(p2)]
            _hits = []
            for _f in _files:
                for _scope, _line, _name in _mod.scan(str(_f)):
                    _hits.append("%s:%s %s" % (_f.name, _line, _name))
            say("names", "FALSIFIED" if _hits else "CONFIRMED",
                "%d backend file(s); names nothing binds: %d %s"
                % (len(_files), len(_hits), sorted(set(_hits))[:3]))

    # --- #1203mi -----------------------------------------------------------------------
    # The scraper kept the live page's inline style, and a root <svg> positioned out of flow
    # draws its paths outside its own viewport (Chromium: 0 opaque px of 4096, 1105 without
    # it). Corpus before the fix: 411 instances, 3 distinct names, 137 runs.
    _pos_mi = []
    for _f in (pub.rglob("*.svg") if pub.is_dir() else []):
        try:
            _m = re.search(r"<svg\b[^>]*>", _f.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        if not _m:
            continue
        _st = re.search(r'style="([^"]*)"', _m.group(0))
        if _st and re.search(r"(^|;)\s*position\s*:", _st.group(1), re.I):
            _pos_mi.append(_f.name)
    say("mi", "FALSIFIED" if _pos_mi else "CONFIRMED",
        "staged SVGs whose ROOT style still declares `position`: %d %s"
        % (len(_pos_mi), sorted(set(_pos_mi))[:3]))

    # --- #1203mh -----------------------------------------------------------------------
    # The #740 capture warning used to claim the console errors reach EVERY screen's
    # deviations; they reach the _blank_screens arm only, and a judged screen gets #1203l8's
    # extracted API paths instead. N-A when the run printed no #740 line.
    _740 = [ln for ln in logtext.split("\n") if "#740 the browser reported" in ln]
    if not _740:
        say("mh", "N-A", "this run printed no #740 capture line")
    else:
        _bad_mh = [ln for ln in _740 if "now in each screen's deviations" in ln]
        say("mh", "FALSIFIED" if _bad_mh else "CONFIRMED",
            "%d #740 line(s); still claiming every screen: %d" % (len(_740), len(_bad_mh)))

    # --- #1203mj -----------------------------------------------------------------------
    # The #743 warning called its own finding inert while #751 blocks the cut on it. A
    # claim about the framework's OWN EMITTED WORDING, which a run never retracts, so the
    # log is the right place to ask (see the #1203mp audit: the question is whether the
    # answer can change mid-run, and this one cannot).
    _743 = [l for l in logtext.split("\n") if "#743 " in l and "FAILED at the delivery cut" in l]
    if not _743:
        say("mj", "N-A", "no run ended with a FAILED task at the cut")
    else:
        _bad_mj = [l for l in _743
                   if "nothing reads them" in l or "Reported, not enforced" in l]
        say("mj", "FALSIFIED" if _bad_mj else "CONFIRMED",
            "%d #743 failed-task line(s); still calling the finding inert: %d"
            % (len(_743), len(_bad_mj)))

    # --- #1203ml -----------------------------------------------------------------------
    # When a build dies on the tar stream, something must now NAME the context. Paired
    # question: the premise (a tar failure happened) and the claim (it was explained).
    _tarfail = [p for p in (run / "logs").glob("compose*failure*.log")
                if (run / "logs").is_dir()
                and re.search(r"missed writing|unexpected EOF",
                              p.read_text(encoding="utf-8", errors="replace"))]
    if not _tarfail:
        say("ml", "N-A", "no build died on the tar stream in this run")
    else:
        _named = logtext.count("#1203ml the build context, not the app")
        say("ml", "CONFIRMED" if _named else "FALSIFIED",
            "%d tar/EOF build failure(s); times the context was named: %d"
            % (len(_tarfail), _named))

    # --- #1203mm -----------------------------------------------------------------------
    # Both halves or neither: anything excluded from the context MUST be mounted back, or
    # the media 404s. Read off the ARTIFACTS (.dockerignore + compose), never the log --
    # this is a question about the project's final state.
    _fe_mm = run / "app" / "frontend"
    _di_mm = _fe_mm / ".dockerignore"
    _cf_mm = run / "docker" / "docker-compose.yml"
    _heavy_mm = []
    _assets_mm = _fe_mm / "public" / "assets"
    if _assets_mm.is_dir():
        for _sub in sorted(_assets_mm.iterdir()):
            if not _sub.is_dir():
                continue
            _b = sum(f.stat().st_size for f in _sub.rglob("*") if f.is_file())
            if _b >= 100 * (1024 ** 2):
                _heavy_mm.append((_sub.name, _b))
    if not _heavy_mm:
        say("mm", "N-A", "no staged media directory over the 100 MB floor")
    else:
        _ditext = _di_mm.read_text(encoding="utf-8", errors="replace") if _di_mm.is_file() else ""
        _cftext = _cf_mm.read_text(encoding="utf-8", errors="replace") if _cf_mm.is_file() else ""
        _unmatched = []
        for _nm, _b in _heavy_mm:
            _excluded = ("public/assets/%s" % _nm) in _ditext
            _mounted = ("/usr/share/nginx/html/assets/%s" % _nm) in _cftext
            if _excluded != _mounted:
                _unmatched.append("%s(excluded=%s mounted=%s)" % (_nm, _excluded, _mounted))
            elif not _excluded:
                _unmatched.append("%s(still in the context)" % _nm)
        # PREMISE (2026-10-17): the pair is only judgeable AFTER the repair has had a turn.
        # `scaffolder.py` rewrites docker/docker-compose.yml from its template on every
        # (re)start -- r190's third resume rewrote it at 05:33 -- while the .dockerignore
        # written by #1203mm lives in the app tree and survives. So between a restart and the
        # next build there is a real window where excluded=True/mounted=False, and reading it
        # then reports a transient as a defect. MEASURED on the previous resume: compose
        # regenerated at 20:07, #1203mm re-injected the mount at 20:10:48 and again at
        # 20:31:29, and the pair read CONFIRMED all evening. This criterion was FALSIFIED by
        # that window at 05:35 with zero build/up calls in the log -- my reading, not the
        # framework's defect.
        #
        # So the claim is checked IN THE LOG, where both facts share a clock: did the repair
        # run BEFORE each build? The tree-pair reading needs a tree and a log from the same
        # instant, and it does not have one -- reading today's tree against yesterday's log
        # reports FALSIFIED for a compose file a restart rewrote hours later.
        # The spawn line is `compose spawn: docker build` / `docker up -d` -- the word
        # "compose" is in the PREFIX, not in the argv the framework echoes. My first pattern
        # required `docker compose build` and matched 0 lines in every log, including ones
        # with 108 builds: calibrate the pattern on the real lines before believing a zero.
        _builds_mm = [m.start() for m in re.finditer(
            r"compose spawn: docker (?:compose )?(?:build|up)\b", logtext)]
        _injects_mm = [m.start() for m in re.finditer(r"#1203mm kept \d+ media dir", logtext)]
        if not _builds_mm:
            say("mm", "N-A",
                "no build/up in this log, so the repair had no turn (tree currently reads %s)"
                % (_unmatched or "both halves present"))
        else:
            _unprotected = [b for b in _builds_mm if not any(i < b for i in _injects_mm)]
            say("mm", "FALSIFIED" if _unprotected else "CONFIRMED",
                "%d heavy media dir(s) %s; %d build/up call(s), %d injection(s), builds with "
                "no preceding injection: %d"
                % (len(_heavy_mm),
                   ", ".join("%s %.0fMB" % (n, b / (1024 ** 2)) for n, b in _heavy_mm),
                   len(_builds_mm), len(_injects_mm), len(_unprotected)))

    # --- #1203mn -----------------------------------------------------------------------
    # The top blocker must quote the words its own records carry. Premise from the ledger,
    # claim checked against the records on disk -- not a log count.
    _mn_prose = []
    _dgl = run / "logs" / "delivery_gate.jsonl"
    if _dgl.is_file():
        for _line in _dgl.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                _d = json.loads(_line)
            except Exception:
                continue
            _v = (_d.get("blocker_prose") or {}).get("validation_ui_evidence_failed")
            if _v:
                _mn_prose.append(" ".join(_v) if isinstance(_v, list) else str(_v))
    _checks_mn = _json(run / "shared" / "hubs" / "codehub_checks.json", {}) or {}
    _have_words = any(
        isinstance(v, dict) and "ui_flow" in str(v.get("name", ""))
        and str(v.get("status", "")).lower() in ("failure", "failed", "fail")
        and str(((v.get("evidence") or {}) if isinstance(v.get("evidence"), dict) else {})
                .get("summary") or "").strip()
        for v in _checks_mn.values())
    if not _mn_prose:
        say("mn", "N-A", "this run never emitted the ui-evidence blocker")
    elif not _have_words:
        say("mn", "N-A", "the blocker fired but no failing ui_flow record carries words")
    else:
        _silent = sum(p.count("no summary recorded") for p in _mn_prose)
        say("mn", "FALSIFIED" if _silent else "CONFIRMED",
            "%d blocker entr(ies) while records DO carry words; 'no summary recorded': %d"
            % (len(_mn_prose), _silent))

    # --- #1203mu (2026-10-16) ----------------------------------------------------------
    # Pre-registered: a resume launched with the brief the checkpoint holds must NOT
    # recompile the reference spec. PREDICTION: zero #1202eo lines, and if #1203mu speaks at
    # all it is a refusal BEFORE any milestone work (which would mean the launch was wrong).
    # FALSIFIED by: #1202eo present in a resume log whose brief came from .checkpoint.
    _eo = logtext.count("#1202eo RECOMPILING")
    _mu = logtext.count("#1203mu")
    _resumed = "Resuming from checkpoint" in logtext
    if not _resumed:
        say("mu", "N-A", "not a resume log")
    else:
        say("mu", "FALSIFIED" if _eo else "CONFIRMED",
            "#1202eo recompile notices: %d; #1203mu lines: %d" % (_eo, _mu))

    # --- #1203mv (2026-10-16) ----------------------------------------------------------
    # Pre-registered: every path #1202sd declines is named. PREDICTION: usually silent (3 of
    # 102 delivered App.jsx carry one), and when it speaks the path it names carries ? or &.
    _mv = [ln for ln in logtext.splitlines() if "#1203mv" in ln]
    if not _mv:
        say("mv", "N-A", "no query-string <Route path> in this run")
    else:
        _ok = all(("?" in ln or "&" in ln) for ln in _mv)
        say("mv", "CONFIRMED" if _ok else "FALSIFIED",
            "%d declined route(s) named; all carry a query string: %s" % (len(_mv), _ok))

    # --- #1203mw (2026-10-16) ----------------------------------------------------------
    # Pre-registered: media the BACKEND references but that is not staged is reported, even
    # when the path lives in custom_routes.py. PREDICTION on r190's tree: the one missing
    # avatar (/assets/real_avatars/mayarios.jpg, in custom_routes.py) is named by the
    # shipped detector. FALSIFIED by: the detector returning [] while the tree still has an
    # unresolvable backend reference.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agent"))
        from env_generator.llm_generator.multi_agent.runtime.frontend_scaffold import (
            unstaged_seed_media_1202xn as _un1203mw)
        _miss = _un1203mw(run) or []
        import re as _re1203mw
        _refs, _absent = set(), []
        _rx = _re1203mw.compile(
            r"[\"'](/assets/[A-Za-z0-9_./-]+\.(?:mp4|webm|mov|m4v|jpg|jpeg|png|webp|gif))[\"']")
        for _f in (run / "app" / "backend").rglob("*.py"):
            if "__pycache__" in _f.parts:
                continue
            try:
                _refs |= set(_rx.findall(_f.read_text(errors="ignore")))
            except Exception:
                pass
        _absent = [r for r in sorted(_refs)
                   if not (pub.parent / r.lstrip("/")).is_file()
                   and not r.startswith(("/assets/icons/", "/assets/placeholders/"))]
        if not _absent:
            say("mw", "N-A", "every backend media reference resolves in this tree")
        else:
            _named = [a for a in _absent if any(a in m for m in _miss)]
            say("mw", "CONFIRMED" if len(_named) == len(_absent) else "FALSIFIED",
                "%d unresolvable backend reference(s), %d named by the detector%s"
                % (len(_absent), len(_named),
                   "" if len(_named) == len(_absent)
                   else "; unnamed: %s" % [a for a in _absent if a not in _named][:3]))
    except Exception as _e1203mw:
        say("mw", "N-A", "could not evaluate: %s" % _e1203mw)

    # --- #1203mx (2026-10-17) ----------------------------------------------------------
    # Pre-registered: a chain step that 404s on an id the seed declares for ANOTHER table
    # must now be told which table owns it. PREDICTION on r190's third resume: the
    # `for_you_feed_to_sound_detail` failure either disappears (the lane fixed the capture)
    # or carries "IS an id in `feed`". FALSIFIED by: a "does not resolve" failure whose value
    # is owned by exactly one other seeded table and that says nothing about it.
    try:
        import json as _j1203mx
        _ch = _json(run / "shared" / "hubs" / "registryhub_verification_chains.json", {}) or {}
        _recs = _ch if isinstance(_ch, list) else list(_ch.values())
        _seed = _json(run / "app" / "backend" / "seed_data.json", {}) or {}
        _ids = {t: {str(r.get("id")) for r in rows if isinstance(r, dict)}
                for t, rows in (_seed.items() if isinstance(_seed, dict) else [])
                if isinstance(rows, list) and rows and isinstance(rows[0], dict)
                and "id" in rows[0]}
        _unres, _named = 0, 0
        for _c in _recs:
            if not isinstance(_c, dict):
                continue
            for _b in ((_c.get("last_result") or {}).get("broken") or []):
                _b = str(_b)
                if "does not resolve" not in _b:
                    continue
                _m = re.search(r"TABLE `([a-z_]+)`", _b)
                _tgt = _m.group(1) if _m else None
                _mp = re.search(r"(?:GET|POST|PATCH|PUT|DELETE) (/\S+?) →", _b)
                _own = None
                for _s in ([x for x in _mp.group(1).split("?")[0].split("/") if x] if _mp else []):
                    if _tgt and _s in _ids.get(_tgt, set()):
                        continue
                    _o = sorted(t for t, v in _ids.items() if _s in v and t != _tgt)
                    if len(_o) == 1:
                        _own = (_s, _o[0])
                        break
                if not _own:
                    continue
                _unres += 1
                if "IS an id in" in _b:
                    _named += 1
        if not _unres:
            say("mx", "N-A", "no chain step failed on an id another seeded table owns")
        else:
            say("mx", "CONFIRMED" if _named == _unres else "FALSIFIED",
                "%d attributable chain failure(s), %d name the owning table" % (_unres, _named))
    except Exception as _e1203mx:
        say("mx", "N-A", "could not evaluate: %s" % _e1203mx)

    # --- #1203my (2026-10-17) ----------------------------------------------------------
    # Pre-registered, and narrow on purpose: the stored record does not keep the request
    # BODY, so "every body-side failure is attributed" is not decidable from the artifact.
    # What IS decidable is the chain this shipped for -- `comment_panel_comment_readback`
    # sends {"video_id": "feed-1"} and `foreign_body_id_owner_1203my` returns
    # ('video_id','feed-1','videos','feed') against r190's seed on disk. PREDICTION: either
    # that chain stops failing (the lane fixed the capture, as it did for #1203mx within the
    # hour) or its failure text carries "THE BODY sent". FALSIFIED by a failure without it.
    try:
        _ch_my = _json(run / "shared" / "hubs" / "registryhub_verification_chains.json", {}) or {}
        _recs_my = _ch_my if isinstance(_ch_my, list) else list(_ch_my.values())
        _target_my = [c for c in _recs_my if isinstance(c, dict)
                      and "comment" in str(c.get("name") or "")]
        _broken_my = [str(b) for c in _target_my
                      for b in ((c.get("last_result") or {}).get("broken") or [])
                      if "does not resolve" in str(b)]
        _bodies_my = logtext.count("THE BODY sent")
        if not _broken_my:
            say("my", "N-A", "no comment-chain step failed on an unresolved id (%d body "
                             "attribution(s) in the log)" % _bodies_my)
        else:
            _said = sum(1 for b in _broken_my if "THE BODY sent" in b)
            say("my", "CONFIRMED" if _said == len(_broken_my) else "FALSIFIED",
                "%d comment-chain failure(s) on an unresolved id, %d name the body field"
                % (len(_broken_my), _said))
    except Exception as _e1203my:
        say("my", "N-A", "could not evaluate: %s" % _e1203my)

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
