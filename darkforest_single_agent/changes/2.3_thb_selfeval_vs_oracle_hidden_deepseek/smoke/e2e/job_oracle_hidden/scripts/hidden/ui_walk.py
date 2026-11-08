#!/usr/bin/env python3
"""H1b, hidden: a deterministic browser walk over the spec's screens and controls, as a user would do it.

usage: PLAYWRIGHT_BROWSERS_PATH=... ui_walk.py <backend_url> <frontend_url> <out_dir>

The agent never sees this. It logs in through the UI with its own account (two profiles made through the API), then
reaches screens by clicking, and uses the controls the spec says must work.
- The routes the spec names are checked: /browse, /shows, /movies, /games, /new, /browse/languages, /watch/:id.
- Controls are found by role, label and visible text, the way the spec names them (Sign In, Play, My List, search,
  Sign out), never by a submission's CSS classes.
Failure screenshots go to <out_dir>/ for adjudication. Writes <out_dir>/ui_walk.json.
"""
import json, os, random, re, sys

import requests
from playwright.sync_api import sync_playwright

DATASET = "/home/user/project/shabi_forest/benchmarks/env-gen/design_inputs/netflix/dataset/titles.json"
NAV = [("Home", r"/browse/?$"), ("Shows", r"/shows/?$"), ("Movies", r"/movies/?$"), ("Games", r"/games/?$"),
       ("New & Popular", r"/new/?$"), ("My List", r"list"), ("Browse by Languages", r"/browse/languages/?$")]


def account_button(page):
    """The header's account-menu button, not a profile switch such as a Kids link; None if there is none."""
    for rx in (r"account", r"profile menu|user menu|^menu$", r"^(?!.*(switch|kids)).*profile"):
        cand = page.get_by_role("button", name=re.compile(rx, re.I))
        if cand.count():
            return cand
    return None


class Walk:
    def __init__(self, be, fe, out):
        self.be, self.fe, self.out, self.checks, self.errors, self.broken = be.rstrip("/"), fe.rstrip("/"), out, [], [], set()
        os.makedirs(out, exist_ok=True)
        self.n = random.randint(10 ** 6, 10 ** 7)

    def check(self, name, ok, detail="", page=None):
        self.checks.append({"name": name, "ok": bool(ok), "detail": str(detail)[:300]})
        if not ok and page is not None:
            try:
                page.screenshot(path=os.path.join(self.out, f"fail_{len(self.checks):02d}.png"))
            except Exception:
                pass

    @staticmethod
    def search_word():
        """A word that occurs in exactly one dataset title (the task's own catalog, not a submission's)."""
        ds = json.load(open(DATASET))
        ds = ds if isinstance(ds, list) else ds.get("titles") or next(iter(ds.values()))
        words = {}
        for d in ds:
            if not d.get("genres"):  # a title without genres is a data edge case, not a search probe
                continue
            for w in set(re.findall(r"[A-Za-z]{6,}", d.get("name", ""))):
                words.setdefault(w.lower(), []).append(d["name"])
        return sorted(w for w, v in words.items() if len(v) == 1)[0]

    def account(self):
        email, pw = f"w{self.n}@hidden-walk.test", f"Walk-{self.n}!"
        tok = requests.post(self.be + "/auth/register", json={"email": email, "password": pw, "name": "Walker"},
                            timeout=20).json().get("access_token")
        for name in ("Walk One", "Walk Two"):
            requests.post(self.be + "/api/profiles", json={"name": name, "avatar": "blue", "is_kids": False},
                          headers={"Authorization": f"Bearer {tok}"}, timeout=20)
        return email, pw

    def settle(self, page, ms=1500):
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(ms)

    def note_images(self, page):
        try:
            bad = page.evaluate("() => [...document.images].filter(i => i.complete && i.naturalWidth === 0 && "
                                "i.getAttribute('src')).map(i => i.getAttribute('src'))")
            self.broken.update(bad)
        except Exception:
            pass

    def loaded_images(self, page):
        return page.evaluate("() => [...document.images].filter(i => i.complete && i.naturalWidth > 0 && "
                             "i.getBoundingClientRect().width > 40).length")

    def click_text(self, page, text, scope="header, nav, [role=navigation], body"):
        for sel in [f"{s} >> text='{text}'" for s in scope.split(", ")]:
            loc = page.locator(sel)
            for i in range(min(loc.count(), 5)):
                if loc.nth(i).is_visible():
                    loc.nth(i).click()
                    return True
        return False

    def pick_profile(self, page, name):
        if "/profiles" not in page.url:
            page.goto(self.fe + "/profiles")
            self.settle(page)
        loc = page.get_by_text(name, exact=True)
        if loc.count():
            loc.first.click()
            self.settle(page)
            return True
        return False

    def run(self):
        email, pw = self.account()
        with sync_playwright() as p:
            b = p.chromium.launch()
            ctx = b.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            page.on("console", lambda m: m.type == "error" and self.errors.append(m.text[:200]))
            page.on("pageerror", lambda e: self.errors.append("pageerror: " + str(e)[:200]))
            try:
                self.steps(page, email, pw)
            except Exception as e:
                self.check("walk did not crash", False, repr(e), page)
            b.close()
        self.check("no broken images on visited pages", not self.broken, sorted(self.broken)[:5])
        self.check("no console errors during the walk", not self.errors, self.errors[:5])
        res = {"checks": self.checks, "passed": sum(c["ok"] for c in self.checks), "total": len(self.checks)}
        json.dump(res, open(os.path.join(self.out, "ui_walk.json"), "w"), indent=1)
        return res

    def steps(self, page, email, pw):
        page.goto(self.fe + "/")
        self.settle(page)
        txt = page.inner_text("body").lower()
        self.check("landing renders with Sign In and an email field", "sign in" in txt and page.locator("input").count() > 0,
                   txt[:80], page)
        self.note_images(page)
        # sign in through the landing page's Sign In, as a visitor would
        if not self.click_text(page, "Sign In"):
            page.goto(self.fe + "/login")
        self.settle(page)
        self.check("Sign In leads to /login", "/login" in page.url, page.url, page)
        page.locator("input[type=email], input[name*=email i], input[autocomplete=email], input[type=text]").first.fill(email)
        page.locator("input[type=password]").first.fill(pw)
        btn = page.get_by_role("button", name=re.compile(r"sign in|log in|login", re.I))
        (btn.first.click() if btn.count() else page.keyboard.press("Enter"))
        self.settle(page, 2500)
        self.check("signing in leaves the login page", "/login" not in page.url, page.url, page)
        self.check("the profile picker shows the account's profiles",
                   self.pick_profile(page, "Walk One"), page.url, page)
        if "/browse" not in page.url:
            page.goto(self.fe + "/browse")
            self.settle(page)
        self.settle(page, 2500)
        hero = page.evaluate("() => Math.max(0, ...[...document.querySelectorAll('img, video, [style*=background]')]"
                             ".map(e => e.getBoundingClientRect().width))")
        self.check("browse home has a hero billboard (>=60% wide)", hero >= 0.6 * 1440, hero, page)
        n = self.loaded_images(page)
        self.check("browse home shows poster rails (>=10 images loaded)", n >= 10, n, page)
        self.note_images(page)
        for label, rx in NAV:
            page.goto(self.fe + "/browse")
            self.settle(page, 800)
            ok = self.click_text(page, label)
            self.settle(page)
            body = page.inner_text("body")
            good = ok and re.search(rx, page.url) and len(body) > 40 and self.loaded_images(page) + ("list" in rx) > 0
            self.check(f"nav '{label}' opens its screen", good, page.url, page)
            self.note_images(page)
        for name, fn in (("title detail and My List", self.step_detail_my_list), ("search", self.step_search),
                         ("player", self.step_player), ("account menu", self.step_account)):
            try:
                fn(page)
            except Exception as e:  # one broken screen must not hide the rest of the walk
                self.check(f"the {name} steps ran", False, repr(e)[:200], page)

    def step_detail_my_list(self, page):
        self.click_text(page, "My List")
        self.settle(page)
        n0 = self.loaded_images(page)  # profile one's list before adding (empty, unless the app leaks other rows)
        page.goto(self.fe + "/browse")
        self.settle(page, 2000)
        cards = page.locator("main img, [class*=row] img, [class*=rail] img, section img")
        opened = False
        for i in range(min(cards.count(), 12)):
            c = cards.nth(i)
            box = c.bounding_box()
            if c.is_visible() and box and 80 < box["width"] < 600 and box["y"] > 400:
                c.hover()
                page.wait_for_timeout(600)
                c.click()
                self.settle(page)
                opened = page.get_by_role("dialog").count() > 0 or "/title" in page.url
                if opened:
                    break
                page.keyboard.press("Escape")
        play = page.get_by_role("button", name=re.compile(r"^\s*play\b", re.I))
        self.check("clicking a poster opens the title detail with Play", opened and play.count() > 0, page.url, page)
        dlg = page.get_by_role("dialog")
        scope = dlg.first if dlg.count() else page  # the detail's own control, not a rail's "Scroll My List" arrow
        add = scope.get_by_role("button", name=re.compile(r"^(?!scroll).*(my list|add to list)|^\+$|^add$", re.I))
        had_add = add.count() > 0  # counted now: the button is gone once we leave the detail
        if had_add:
            add.first.click(timeout=10000)
            page.wait_for_timeout(1500)
        page.keyboard.press("Escape")
        self.click_text(page, "My List")
        self.settle(page)
        n1 = self.loaded_images(page)
        self.pick_profile(page, "Walk Two")
        self.click_text(page, "My List")
        self.settle(page)
        n2 = self.loaded_images(page)
        self.check("+ My List from the detail shows up on My List", had_add and n1 > n0, f"{n0} -> {n1}", page)
        self.check("another profile's My List does not show it", had_add and n1 > n0 and n2 < n1, f"{n1} vs {n2}", page)

    def step_search(self, page):
        # open it from the header, type where the focus lands (or the header's first visible input)
        page.goto(self.fe + "/browse")
        self.settle(page)
        s = page.get_by_role("button", name=re.compile("search", re.I))
        (s.first.click() if s.count() else None)
        page.wait_for_timeout(600)
        word = self.search_word()
        focused = page.evaluate("() => document.activeElement && document.activeElement.tagName === 'INPUT'")
        box = None if focused else page.locator("header input:visible, nav input:visible, input[type=search]:visible")
        if focused or (box is not None and box.count()):
            (page.keyboard.type(word) if focused else box.first.fill(word))
            page.keyboard.press("Enter")
            self.settle(page, 2000)
        self.check("search finds a title by name", (focused or (box is not None and box.count()))
                   and word.lower() in page.inner_text("body").lower() and self.loaded_images(page) >= 1, page.url, page)

    def step_player(self, page):
        page.goto(self.fe + "/browse")
        self.settle(page, 2000)
        play = page.get_by_role("button", name=re.compile(r"^\s*play\b", re.I))
        if play.count():
            play.first.click()
            self.settle(page, 2500)
        src = page.evaluate("() => { const v = document.querySelector('video'); return v ? (v.currentSrc || v.src) : null }")
        ok_src = False
        if src:
            try:
                ok_src = requests.get(src if src.startswith("http") else self.fe + src, headers={"Range": "bytes=0-1023"},
                                      timeout=20).status_code in (200, 206)
            except Exception:
                pass
        self.check("Play opens /watch/:id with a loadable video", re.search(r"/watch/\w+", page.url) and ok_src,
                   f"{page.url} {src}", page)
        back = page.get_by_role("button", name=re.compile(r"back", re.I))
        (back.first.click() if back.count() else page.go_back())
        self.settle(page)
        self.check("the player's back returns to the browse page", "/watch" not in page.url, page.url, page)

    def step_account(self, page):
        page.goto(self.fe + "/browse")
        self.settle(page)
        menu = account_button(page)
        if menu is not None:
            menu.first.hover()
            page.wait_for_timeout(500)
            if not page.get_by_text(re.compile("sign out", re.I)).count():
                menu.first.click()
                page.wait_for_timeout(500)
        so = page.get_by_text(re.compile(r"^\s*sign out", re.I))
        self.check("the account menu offers Sign out", so.count() > 0, "", page)
        if so.count():
            so.first.click()
            self.settle(page)
            page.goto(self.fe + "/browse")
            self.settle(page)
            self.check("after Sign out, /browse is no longer reachable",
                       "/browse" not in page.url or "sign in" in page.inner_text("body").lower(), page.url, page)


if __name__ == "__main__":
    r = Walk(sys.argv[1], sys.argv[2], sys.argv[3]).run()
    for c in r["checks"]:
        print(("PASS " if c["ok"] else "FAIL ") + c["name"] + ("" if c["ok"] else f"  ({c['detail']})"))
    print(f"{r['passed']}/{r['total']}")
