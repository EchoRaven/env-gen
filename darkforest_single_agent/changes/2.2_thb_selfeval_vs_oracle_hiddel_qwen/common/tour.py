#!/usr/bin/env python3
"""In-person evaluation aid (Phase 4): drive a running app through its real UI like a person and screenshot each step.

usage: PLAYWRIGHT_BROWSERS_PATH=<.envs>/cache/ms-playwright <thb-validator python> -I -B tour.py <frontend_url> <out_dir>
       [player_route_template, e.g. /watch/{id}: used only when the Play button cannot be pressed]

No app-specific routes or storage keys: a fresh account is registered through the UI (or the API if the UI has no
sign-up), signed in through the visible form (one- or two-step), then the first profile is picked, the header nav
links are visited, a title card is opened, and Play is pressed. Each step writes <NN>_<name>.png; tour.json records
URLs, the step log, console errors and failed requests. Nothing here scores anything or calls an LLM.
"""
import json, os, random, re, sys
from playwright.sync_api import sync_playwright

FE, OUT = sys.argv[1].rstrip("/"), sys.argv[2]
os.makedirs(OUT, exist_ok=True)
log, errors, failed, n = [], [], [], [0]


def shot(page, name):
    n[0] += 1
    page.wait_for_timeout(1200)
    page.screenshot(path=os.path.join(OUT, f"{n[0]:02d}_{name}.png"))
    log.append({"step": n[0], "name": name, "url": page.url})
    print(n[0], name, page.url, flush=True)


def click_text(page, pattern, roles=("button", "link")):
    for role in roles:
        loc = page.get_by_role(role, name=re.compile(pattern, re.I))
        if loc.count():
            loc.first.click(timeout=5000)
            return True
    return False


def sign_in(page, email, pw):
    page.locator("input[type=email], input[name*=email i], input[autocomplete*=email i]").first.fill(email, timeout=10000)
    if not page.locator("input[type=password]").count():
        click_text(page, r"continue|next|sign in")
        page.wait_for_timeout(1500)
    page.locator("input[type=password]").first.fill(pw, timeout=10000)
    page.locator("input[type=password]").first.press("Enter")
    page.wait_for_timeout(3000)


def main():
    email, pw = f"tour{random.randint(10**5, 10**6)}@example.com", "TourPass!2345"
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.on("console", lambda m: m.type == "error" and errors.append(m.text[:300]))
        page.on("requestfailed", lambda r: failed.append(r.url[:200]))
        page.on("response", lambda r: r.status >= 400 and failed.append(f"{r.status} {r.url[:200]}"))
        page.goto(FE + "/", wait_until="networkidle")
        shot(page, "landing")
        # register through the API (the form flows differ too much; the API path is the contract's)
        import urllib.request
        req = urllib.request.Request(FE + "/auth/register", data=json.dumps(
            {"email": email, "password": pw, "name": "Tour"}).encode(), headers={"Content-Type": "application/json"})
        try:
            log.append({"register": urllib.request.urlopen(req, timeout=20).status})
        except Exception as e:
            log.append({"register_error": str(e)[:200]})
        if not click_text(page, r"^sign in$|log in"):
            page.goto(FE + "/login", wait_until="networkidle")
        page.wait_for_timeout(1000)
        shot(page, "login")
        sign_in(page, email, pw)
        shot(page, "after_sign_in")
        # pick (or create) a profile
        if page.get_by_text(re.compile(r"who.s watching", re.I)).count():
            for c in page.locator("button, a, [role=button], [tabindex='0']").all():
                try:
                    t = (c.inner_text(timeout=1000) or "").strip()
                except Exception:
                    continue
                if t and not re.search(r"manage|add|sign out|edit|done", t, re.I):
                    log.append({"profile_clicked": t[:40]})
                    c.click(timeout=5000)
                    page.wait_for_timeout(2500)
                    break
        page.wait_for_load_state("networkidle")
        shot(page, "home")
        page.mouse.wheel(0, 800)
        shot(page, "home_rows")
        home = page.url
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
            bb = c.bounding_box()  # click where a person would (a hover overlay covers the poster)
            page.mouse.move(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
            page.wait_for_timeout(800)
            shot(page, "card_hover")
            page.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 3)
            page.wait_for_timeout(1500)
            shot(page, "title_open")
            pb = page.get_by_role("button", name=re.compile(r"^\W*play\b", re.I))
            ok = False
            if pb.count():
                try:
                    pb.first.click(timeout=4000)
                    ok = True
                except Exception:  # covered by another layer: click where a person would and see what happens
                    bb = pb.first.bounding_box()
                    before = page.url
                    page.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
                    page.wait_for_timeout(2000)
                    ok = page.url != before or page.locator("video").count() > 0
                    log.append({"play_button_covered": True, "mouse_click_started_player": ok})
            if not ok and len(sys.argv) > 3:  # optional player route template, e.g. /watch/{id}, to check the player
                page.goto(FE + sys.argv[3].format(id=page.url.rstrip("/").split("/")[-1]), wait_until="networkidle")
                log.append({"player_opened_by_route": page.url})
                ok = True
            if ok:
                page.wait_for_timeout(3000)
                shot(page, "player")
                v = page.locator("video")
                log.append({"video": v.count() and v.first.evaluate(
                    "v => ({src: v.currentSrc, t: v.currentTime, paused: v.paused, err: v.error && v.error.code})")})
        b.close()
    json.dump({"frontend": FE, "account": email, "log": log, "console_errors": errors[:50],
               "failed_requests": failed[:80]}, open(os.path.join(OUT, "tour.json"), "w"), indent=1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.append({"tour_error": str(e)[:800]})
        json.dump({"frontend": FE, "log": log, "console_errors": errors[:50], "failed_requests": failed[:80]},
                  open(os.path.join(OUT, "tour.json"), "w"), indent=1)
        raise
