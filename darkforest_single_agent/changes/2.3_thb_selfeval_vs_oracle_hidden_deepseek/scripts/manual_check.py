"""Phase 4 follow-up to common/tour.py (2.3; not in 2.2). Signs in as the account tour.py registered (tour.json),
creates a first profile if the app asks for one, and presses the Play buttons a person would use: the hero's, and the
one inside an open title view (/browse?title=<id> and /title/<id>). Also opens the Browse-by-Languages menu and page.
With --full it first repeats tour.py's steps (nav links, card hover, card click) for apps where tour.py stopped early.
Screens and manual.json go to <tour_dir>/manual/. Nothing is scored; no LLM is called.

usage: PLAYWRIGHT_BROWSERS_PATH=<.envs>/cache/ms-playwright <thb-validator python> -I -B scripts/manual_check.py \
       <frontend_url> <tour_dir> [title_id] [--full]"""
import json, os, re, sys
from playwright.sync_api import sync_playwright

FE, D = sys.argv[1].rstrip("/"), sys.argv[2]
TID = sys.argv[3] if len(sys.argv) > 3 and not sys.argv[3].startswith("--") else "48"
OUT = os.path.join(D, "manual")
os.makedirs(OUT, exist_ok=True)
email = json.load(open(os.path.join(D, "tour.json")))["account"]
pw = "TourPass!2345"
log, n = [], [0]


def shot(page, name):
    n[0] += 1
    page.wait_for_timeout(1500)
    page.screenshot(path=os.path.join(OUT, f"m{n[0]:02d}_{name}.png"))
    log.append({"step": n[0], "name": name, "url": page.url})
    print(n[0], name, page.url, flush=True)


def video_state(page):
    v = page.locator("video")
    return v.count() and v.first.evaluate(
        "v => ({src: v.currentSrc, t: v.currentTime, paused: v.paused, err: v.error && v.error.code})")


def signed_in_home(page):
    page.goto(FE + "/login", wait_until="networkidle")
    page.locator("input[type=email], input[name*=email i], input[autocomplete*=email i]").first.fill(email)
    if not page.locator("input[type=password]").count():
        for role in ("button", "link"):
            loc = page.get_by_role(role, name=re.compile(r"continue|next|sign in", re.I))
            if loc.count():
                loc.first.click()
                break
        page.wait_for_timeout(1500)
    page.locator("input[type=password]").first.fill(pw)
    page.locator("input[type=password]").first.press("Enter")
    page.wait_for_timeout(3000)
    if page.get_by_text(re.compile(r"add a profile", re.I)).count():  # fresh account without a profile: create one
        shot(page, "add_profile_dialog")
        page.locator("input:not([type=checkbox]):not([type=radio]):not([type=hidden])").last.fill("Tour")
        page.get_by_role("button", name=re.compile(r"^continue$|^save$|^create", re.I)).first.click()
        page.wait_for_timeout(2500)
        log.append({"profile_created": page.url})
        shot(page, "after_profile_create")
    if page.get_by_text(re.compile(r"who.s watching", re.I)).count():
        page.get_by_text("Tour", exact=True).first.click()
        page.wait_for_timeout(2500)
    page.wait_for_load_state("networkidle")
    return page.url


def tour_rest(page, home):
    shot(page, "home")
    page.mouse.wheel(0, 800)
    shot(page, "home_rows")
    links = []
    for a in page.locator("header a, nav a").all()[:12]:
        try:
            t, h = (a.inner_text(timeout=1000) or "").strip(), a.get_attribute("href")
        except Exception:
            continue
        if t and h and h.startswith("/") and (t, h) not in links:
            links.append((t, h))
    log.append({"nav_links": links})
    for t, h in links:
        page.goto(FE + h, wait_until="networkidle")
        shot(page, "nav_" + re.sub(r"\W+", "_", t.lower())[:24])
    page.goto(home, wait_until="networkidle")
    page.wait_for_timeout(1500)
    cards = page.locator("img[src*=poster], img[src*=backdrop], [class*=card i] img")
    log.append({"cards_on_home": cards.count()})
    if cards.count():
        c = cards.nth(min(2, cards.count() - 1))
        c.scroll_into_view_if_needed(timeout=5000)
        bb = c.bounding_box()
        page.mouse.move(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
        page.wait_for_timeout(800)
        shot(page, "card_hover")
        page.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 3)
        page.wait_for_timeout(1500)
        shot(page, "card_click")


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_context(viewport={"width": 1440, "height": 900}).new_page()
    errors = []
    page.on("console", lambda m: m.type == "error" and errors.append(m.text[:300]))
    home = signed_in_home(page)
    log.append({"home": home})
    if "--full" in sys.argv:
        tour_rest(page, home)
        page.goto(home, wait_until="networkidle")
    # 1. hero Play (the first visible Play button on home)
    pb = page.get_by_role("button", name=re.compile(r"^\W*play\b", re.I))
    log.append({"play_buttons_on_home": pb.count()})
    if pb.count():
        try:
            pb.first.click(timeout=5000)
            page.wait_for_timeout(3000)
            log.append({"hero_play": {"url": page.url, "video": video_state(page)}})
        except Exception as e:
            log.append({"hero_play_error": str(e)[:200]})
        shot(page, "hero_play")
    # 2. title view by URL, then its own Play button (the last visible Play button on the page)
    for route in (f"/browse?title={TID}", f"/title/{TID}"):
        page.goto(FE + route, wait_until="networkidle")
        shot(page, "title_" + re.sub(r"\W+", "_", route)[:30])
        dlg = page.locator("[role=dialog]")
        scope = dlg.first if dlg.count() else page
        pb = scope.get_by_role("button", name=re.compile(r"^\W*play\b", re.I))
        vis = [i for i in range(pb.count()) if pb.nth(i).is_visible()]
        log.append({"route": route, "dialog": dlg.count(), "visible_play": len(vis)})
        if vis:
            before = page.url
            try:
                pb.nth(vis[-1]).click(timeout=5000)
                page.wait_for_timeout(3000)
                log.append({"title_play": {"from": route, "url": page.url, "changed": page.url != before,
                                           "video": video_state(page)}})
            except Exception as e:
                log.append({"title_play_error": {"from": route, "err": str(e)[:300]}})
            shot(page, "title_play_" + re.sub(r"\W+", "_", route)[:30])
    # 3. Browse by Languages menu
    page.goto(home, wait_until="networkidle")
    m = page.get_by_text(re.compile(r"browse by languages", re.I))
    if m.count():
        try:
            m.first.click(timeout=5000)
            page.wait_for_timeout(1500)
            shot(page, "languages_menu")
            if "/languages" not in page.url:
                page.goto(FE + "/browse/languages", wait_until="networkidle")
            shot(page, "languages_page")
        except Exception as e:
            log.append({"languages_error": str(e)[:200]})
    b.close()
    json.dump({"account": email, "log": log, "console_errors": errors[:50]},
              open(os.path.join(OUT, "manual.json"), "w"), indent=1)
    print(json.dumps(log, indent=1)[:3000])
    print("console errors:", errors[:10])
