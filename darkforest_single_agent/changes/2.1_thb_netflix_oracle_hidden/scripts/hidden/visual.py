#!/usr/bin/env python3
"""H3, hidden: env-gen's visual-fidelity judgment of each reference screen, with Claude Code (subscription) as the judge.

usage:
  PLAYWRIGHT_BROWSERS_PATH=... visual.py capture <backend_url> <frontend_url> <out_dir> [convention_json]
  visual.py judge <out_dir>

capture: logs in through the UI with its own account and two API-made profiles, puts four titles on the first
profile's My List (through the API, with the profile convention H1 detected), then reproduces each of the 20 reference
states at the reference size (1920x1107):
- the URL states the spec names;
- the modal, the hover card, the menus and the rate dialog, reached by role, label and text.
A state it cannot reach is recorded as capture_missing and left out of the mean, as env-gen does.

judge: env-gen's own prompt (`_JUDGE_INSTRUCTIONS` with `_rubric_block()`) and parser (`_parse_verdict`), imported
from the frozen repo, with judge_repeats independent judgments per screen. The judge is a `claude -p` call in the
baseline bwrap sandbox, with only the Read tool and only the two images in its workspace. A judgment whose JSON
cannot be parsed is retried once, then recorded as missing rather than as 0 (env-gen's #466 failure mode).
Writes <out_dir>/visual.json.
"""
import json, os, random, re, shutil, statistics, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

EXP = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
X = json.load(open(os.path.join(EXP, "config.json")))
T = "/home/user/project/shabi_forest/benchmarks/env-gen"
REF = f"{T}/design_inputs/netflix/references"
W, H = 1920, 1107


# ---------------------------------------------------------------- capture
def capture(be, fe, out, conv=None, only=None):
    """only: a set of screen names to re-capture; the other screens keep their earlier captures."""
    import requests
    from playwright.sync_api import sync_playwright
    import ui_walk
    os.makedirs(os.path.join(out, "shots"), exist_ok=True)
    n = random.randint(10 ** 6, 10 ** 7)
    email, pw = f"v{n}@hidden-visual.test", f"Vis-{n}!"
    tok = requests.post(be + "/auth/register", json={"email": email, "password": pw, "name": "Visual Checker"}, timeout=20).json()["access_token"]
    hdr = {"Authorization": f"Bearer {tok}"}
    pid = None
    for name in ("Vis One", "Vis Two"):  # never the account name: apps may auto-create a profile named after it
        r = requests.post(be + "/api/profiles", json={"name": name, "avatar": "blue", "is_kids": False}, headers=hdr, timeout=20)
        js = r.json() if r.ok else {}
        pid = pid or (js.get("item", js) or {}).get("id")
    titles = requests.get(be + "/api/titles", headers=hdr, timeout=20).json()
    titles = titles.get("items", titles) if isinstance(titles, dict) else titles
    if conv and pid:
        kind, key = conv
        h, params = dict(hdr), {}
        (h.__setitem__(key, str(pid)) if kind == "header" else params.__setitem__(key, str(pid)))
        for t in titles[:4]:
            requests.post(be + "/api/my-list", json={"title_id": t["id"]}, headers=h, params=params, timeout=20)
    genres = requests.get(be + "/api/genres", headers=hdr, timeout=20).json()
    genres = genres.get("items", genres) if isinstance(genres, dict) else genres
    g = next((x for x in genres if "sport" in x["name"].lower()), None) or next(
        (x for x in genres if re.search(r"tv|drama|action", x["name"], re.I)), genres[0])
    rec = {}
    with sync_playwright() as p:
        b = p.chromium.launch()

        def settle(page, ms=1500):
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(ms)

        def shot(page, name, route):
            if only and name not in only:
                return
            path = os.path.join(out, "shots", name + ".png")
            page.screenshot(path=path)
            rec[name] = {"route": route, "shot": path}

        def missing(name, why):
            if only and name not in only:
                return
            rec[name] = {"capture_missing": True, "why": str(why)[:200]}

        anon = b.new_context(viewport={"width": W, "height": H})
        page = anon.new_page()
        for name, route in (("landing", "/"), ("login", "/login")):
            page.goto(fe + route)
            settle(page)
            shot(page, name, route)
        anon.close()
        ctx = b.new_context(viewport={"width": W, "height": H})
        page = ctx.new_page()
        page.goto(fe + "/login")
        settle(page)
        page.locator("input[type=email], input[name*=email i], input[autocomplete=email], input[type=text]").first.fill(email)
        page.locator("input[type=password]").first.fill(pw)
        btn = page.get_by_role("button", name=re.compile(r"sign in|log in|login", re.I))
        (btn.first.click() if btn.count() else page.keyboard.press("Enter"))
        settle(page, 2500)
        if "/profiles" not in page.url:
            page.goto(fe + "/profiles")
            settle(page)
        prof = page.get_by_text("Vis One", exact=True)
        if prof.count():
            prof.first.click()
            settle(page)

        def go(route, ms=2500):
            page.goto(fe + route)
            settle(page, ms)

        for name, route, scroll in (("browse_home", "/browse", 0), ("browse_home_rows", "/browse", 700),
                                    ("shows", "/shows", 0), ("movies", "/movies", 0), ("games", "/games", 0),
                                    ("new_and_popular", "/new", 0), ("genre_category", f"/browse/genre/{g['id']}", 0),
                                    ("browse_by_languages", "/browse/languages", 0)):
            go(route)
            if scroll:
                page.mouse.wheel(0, scroll)
                page.wait_for_timeout(1200)
            shot(page, name, route)
        try:  # My List, reached by its nav item (the spec names no route)
            go("/browse", 1000)
            loc = page.locator("header, nav").get_by_text("My List", exact=True)
            (loc.first if loc.count() else page.get_by_text("My List", exact=True).first).click()
            settle(page, 2000)
            shot(page, "my_list", page.url.replace(fe, ""))
        except Exception as e:
            missing("my_list", e)

        def hero_button(rx):
            go("/browse")
            bt = page.get_by_role("button", name=re.compile(rx, re.I))
            if not bt.count():
                raise RuntimeError(f"no button {rx}")
            bt.first.click()
            settle(page, 2000)

        try:  # the detail modal of the hero title (More Info), then its episode list
            hero_button(r"more info")
            shot(page, "title_detail", "modal: More Info")
            page.mouse.move(W // 2, H // 2)
            page.mouse.wheel(0, 700)
            page.wait_for_timeout(1200)
            shot(page, "title_episodes", "modal: More Info, scrolled")
        except Exception as e:
            missing("title_detail", e)
            missing("title_episodes", e)
        try:  # rate dialog: a thumbs / rate control in the detail modal
            hero_button(r"more info")
            rb = page.get_by_role("button", name=re.compile(r"rate|thumb|like", re.I))
            if not rb.count():
                raise RuntimeError("no rate control")
            rb.first.hover()
            page.wait_for_timeout(500)
            rb.first.click()
            page.wait_for_timeout(1200)
            shot(page, "rate_dialog", "modal: rate control")
        except Exception as e:
            missing("rate_dialog", e)
        try:  # player, then its controls (mouse over the video)
            hero_button(r"^\s*play\b")
            page.wait_for_timeout(2000)
            shot(page, "player", page.url.replace(fe, ""))
            page.mouse.move(W // 2, H // 2)
            page.mouse.move(W // 2 + 40, H // 2 + 20)
            page.wait_for_timeout(600)
            shot(page, "player_controls", page.url.replace(fe, "") + " (controls)")
        except Exception as e:
            missing("player", e)
            missing("player_controls", e)
        try:  # account menu: the header profile control
            go("/browse", 1500)
            m = ui_walk.account_button(page)
            if m is None:
                raise RuntimeError("no account control")
            m.first.hover()
            page.wait_for_timeout(700)
            if not page.get_by_text(re.compile("sign out", re.I)).count():
                m.first.click()
                page.wait_for_timeout(700)
            shot(page, "account_menu", "header account menu")
        except Exception as e:
            missing("account_menu", e)
        try:  # card hover preview and its expanded preview: hover a rail poster below the hero
            go("/browse")
            page.mouse.wheel(0, 500)  # bring the first rails up from under the hero
            page.wait_for_timeout(1200)
            cards = page.locator("main img, section img, [class*=row] img, [class*=rail] img")
            target = None
            for i in range(min(cards.count(), 40)):
                bb = cards.nth(i).bounding_box()
                if bb and 120 < bb["width"] < 600 and 150 < bb["y"] < H - 250:
                    target = cards.nth(i)
                    break
            if target is None:
                raise RuntimeError("no rail poster in view")
            target.hover()
            page.wait_for_timeout(1800)
            shot(page, "card_hover_preview", "hover a rail poster")
            page.wait_for_timeout(1500)
            shot(page, "card_preview", "hover a rail poster (held)")
        except Exception as e:
            missing("card_hover_preview", e)
            missing("card_preview", e)
        try:  # the Shows page's Genres dropdown
            go("/shows")
            gb = page.get_by_role("button", name=re.compile(r"genres", re.I))
            (gb.first.click() if gb.count() else page.get_by_text(re.compile(r"^\s*genres", re.I)).first.click())
            page.wait_for_timeout(1000)
            shot(page, "shows_genres_menu", "/shows Genres menu")
        except Exception as e:
            missing("shows_genres_menu", e)
        b.close()
    cp = os.path.join(out, "captures.json")
    if only and os.path.exists(cp):
        rec = {**json.load(open(cp)), **rec}
    json.dump(rec, open(cp, "w"), indent=1)
    return rec


# ---------------------------------------------------------------- judge
def _judge_once(out, name, route, rep):
    sys.path[:0] = [f"{T}/agent", f"{T}/agent/env_generator/llm_generator",
                    os.path.join(os.path.dirname(EXP), X["base_experiment"], "scripts")]
    from env_generator.llm_generator.multi_agent.runtime.visual_fidelity import (
        _JUDGE_INSTRUCTIONS, _parse_verdict, _rubric_block)
    import sandbox  # the baseline's bwrap sandbox (0_baxbench_nl2_tests/scripts/sandbox.py, unmodified)
    jrd = os.path.join(out, "judge", f"{name}-{rep}")
    ws = os.path.join(jrd, "workspace")
    os.makedirs(ws, exist_ok=True)
    shutil.copyfile(os.path.join(REF, name + ".jpg"), os.path.join(ws, "1_reference.jpg"))
    shutil.copyfile(os.path.join(out, "shots", name + ".png"), os.path.join(ws, "2_implementation.png"))
    prompt = (_JUDGE_INSTRUCTIONS.format(name=name, route=route, rubric_block=_rubric_block())
              + "\n\nThe two images are files in the current directory. Read `1_reference.jpg` (the FIRST image) and "
                "then `2_implementation.png` (the SECOND image) with the Read tool, then reply with only the JSON.")
    args = ["-p", prompt, "--model", X["hidden"]["judge_model"], "--effort", X["hidden"]["judge_effort"],
            "--output-format", "json", "--dangerously-skip-permissions", "--strict-mcp-config", "--tools", "Read",
            "--no-session-persistence"]
    verdict, raw = None, ""
    for attempt in range(2):
        r = subprocess.run(sandbox.command("nl2", jrd, args), capture_output=True, text=True, timeout=X["hidden"]["judge_timeout_s"])
        try:
            raw = str(json.loads(r.stdout).get("result", ""))
        except Exception:
            raw = r.stdout[-2000:]
        v = _parse_verdict(raw)
        if not any(str(d).startswith("judge ") for d in v.get("deviations") or []):  # "judge returned no JSON" etc.
            verdict = v
            break
    for d in ("home", "claude_overlay"):
        shutil.rmtree(os.path.join(jrd, d), ignore_errors=True)
    open(os.path.join(jrd, "raw.txt"), "w").write(raw)
    return name, rep, verdict


def judge(out, only=None):
    """only: a set of screen names to re-judge; the other screens keep their earlier verdicts from visual.json."""
    cap = json.load(open(os.path.join(out, "captures.json")))
    vp = os.path.join(out, "visual.json")
    old = json.load(open(vp))["screens"] if only and os.path.exists(vp) else {}
    jobs = [(out, n, c["route"], rep) for n, c in cap.items() if not c.get("capture_missing") and (n not in old or n in only)
            for rep in range(X["hidden"]["judge_repeats"])]
    with ThreadPoolExecutor(X["hidden"]["judge_parallel"]) as ex:
        results = list(ex.map(lambda j: _judge_once(*j), jobs))
    screens = {}
    for name, rep, v in results:
        screens.setdefault(name, []).append(v)
    per = {}
    for name in cap:
        if name in old and name not in only:
            per[name] = old[name]
            continue
        vs = [v for v in screens.get(name, []) if v]
        sims = [float(v.get("similarity") or 0.0) for v in vs]
        per[name] = {"capture_missing": bool(cap[name].get("capture_missing")), "judgments": len(vs),
                     "similarity_mean": round(statistics.mean(sims), 3) if sims else None,
                     "similarity_sd": round(statistics.pstdev(sims), 3) if len(sims) > 1 else None,
                     "dimensions": [v.get("dimensions") for v in vs], "deviations": [v.get("deviations") for v in vs]}
    scored = [p["similarity_mean"] for p in per.values() if p["similarity_mean"] is not None]
    res = {"screens": per, "n_screens": len(cap), "n_scored": len(scored),
           "mean_similarity": round(statistics.mean(scored), 3) if scored else None,
           "below_0.55": sorted(n for n, p in per.items() if p["similarity_mean"] is not None and p["similarity_mean"] < 0.55)}
    json.dump(res, open(os.path.join(out, "visual.json"), "w"), indent=1)
    return res


if __name__ == "__main__":
    if sys.argv[1] == "capture":
        r = capture(sys.argv[2].rstrip("/"), sys.argv[3].rstrip("/"), sys.argv[4], json.loads(sys.argv[5]) if len(sys.argv) > 5 else None)
        print({k: ("MISSING " + v["why"]) if v.get("capture_missing") else v["route"] for k, v in r.items()})
    else:
        r = judge(sys.argv[2])
        print(json.dumps({k: (v["similarity_mean"], v["similarity_sd"]) for k, v in r["screens"].items()}, indent=0))
        print("mean", r["mean_similarity"], "scored", r["n_scored"], "/", r["n_screens"], "below 0.55:", r["below_0.55"])
