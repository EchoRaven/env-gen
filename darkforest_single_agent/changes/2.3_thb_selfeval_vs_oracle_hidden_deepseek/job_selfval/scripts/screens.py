#!/usr/bin/env python3
"""Screenshot the running apps of some iterations and put each next to env-gen's reference screenshot.

usage: PLAYWRIGHT_BROWSERS_PATH=<.envs>/cache/ms-playwright <thb-validator python> -I -B scripts/screens.py 1 5
The iterations must be up (scripts/view.py <iter>): frontend on 127.0.0.1:(13000+100*iter), backend 18000+100*iter.

Writes results/visual/it<k>/<screen>.png and results/visual/compare/<screen>.png ([reference | it<a> | it<b> ...],
same height, labelled), plus results/visual/index.html. Pages are logged in as the seeded demo account, profile 1.
This is a picture for people to judge, not a score; nothing here calls an LLM.

Only references that are a page state reachable by URL are captured. Interaction states (account menu, card hover,
card preview, rate dialog, genres menu) are listed in the index as not captured.
"""
import json, os, sys, urllib.request
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

EXP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = "/home/user/project/shabi_forest/benchmarks/env-gen/design_inputs/netflix/references"
OUT = os.path.join(EXP, "results", "visual")
DEMO = {"email": "demo@netflix.local", "password": "netflix123"}
NOT_CAPTURED = ["account_menu", "card_hover_preview", "card_preview", "rate_dialog", "shows_genres_menu"]


def api(base, path, body=None, tok=None):
    r = urllib.request.Request(base + path, data=json.dumps(body).encode() if body else None,
                               method="POST" if body else "GET", headers={"Content-Type": "application/json"})
    if tok:
        r.add_header("Authorization", "Bearer " + tok)
    return json.loads(urllib.request.urlopen(r, timeout=20).read())


def targets(k):
    """screen -> (path, logged_in, scroll_y) for iteration k's app."""
    be = f"http://127.0.0.1:{18000 + 100 * k}"
    tok = api(be, "/auth/login", DEMO)["access_token"]
    genres = api(be, "/api/genres", tok=tok)["items"]
    g = next((x for x in genres if "document" in x["name"].lower()), genres[0])
    series = api(be, "/api/titles?kind=series&limit=1", tok=tok)["items"][0]
    movie = api(be, "/api/titles/trending", tok=tok)["items"][0]
    t = {"landing": ("/", False, 0), "login": ("/login", False, 0), "profiles (no reference)": ("/profiles", True, 0),
         "browse_home": ("/browse", True, 0), "browse_home_rows": ("/browse", True, 700),
         "shows": ("/shows", True, 0), "movies": ("/movies", True, 0), "games": ("/games", True, 0),
         "new_and_popular": ("/new", True, 0), "genre_category": (f"/browse/genre/{g['id']}", True, 0),
         "my_list": ("/my-list", True, 0), "browse_by_languages": ("/browse/languages", True, 0),
         "title_detail": (f"/title/{movie['id']}", True, 0), "title_episodes": (f"/title/{series['id']}", True, 600),
         "player": (f"/watch/{movie['id']}", True, 0), "player_controls": (f"/watch/{movie['id']}", True, -1)}
    return tok, t


def shoot(iters):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for k in iters:
            tok, t = targets(k)
            fe = f"http://127.0.0.1:{13000 + 100 * k}"
            os.makedirs(os.path.join(OUT, f"it{k}"), exist_ok=True)
            for name, (path, logged_in, scroll) in t.items():
                ref = os.path.join(REF, name + ".jpg")
                w, h = Image.open(ref).size if os.path.exists(ref) else (1440, 900)
                ctx = browser.new_context(viewport={"width": w, "height": h})
                if logged_in:
                    ctx.add_init_script(f"localStorage.setItem('nf_token', {json.dumps(tok)});"
                                        "localStorage.setItem('nf_profile', '1');")
                page = ctx.new_page()
                try:
                    page.goto(fe + path, wait_until="networkidle", timeout=30000)
                except Exception:
                    pass
                page.wait_for_timeout(1500)
                if scroll > 0:
                    page.mouse.wheel(0, scroll)
                    page.wait_for_timeout(1200)
                elif scroll < 0:  # show the player's controls
                    page.mouse.move(w // 2, h // 2)
                    page.mouse.move(w // 2 + 10, h // 2 + 10)
                    page.wait_for_timeout(500)
                page.screenshot(path=os.path.join(OUT, f"it{k}", name + ".png"))
                ctx.close()
                print(f"it{k} {name}: {path}")
        browser.close()


def compose(iters):
    os.makedirs(os.path.join(OUT, "compare"), exist_ok=True)
    names = sorted(os.path.splitext(f)[0] for f in os.listdir(os.path.join(OUT, f"it{iters[0]}")))
    H, rows = 600, []
    for name in names:
        ref = os.path.join(REF, name + ".jpg")
        panels = ([("reference (real Netflix)", ref)] if os.path.exists(ref) else []) + \
                 [(f"iteration {k}", os.path.join(OUT, f"it{k}", name + ".png")) for k in iters]
        ims = []
        for label, f in panels:
            im = Image.open(f).convert("RGB")
            im = im.resize((int(im.width * H / im.height), H))
            canvas = Image.new("RGB", (im.width, H + 36), "white")
            canvas.paste(im, (0, 36))
            ImageDraw.Draw(canvas).text((8, 10), label, fill="black")
            ims.append(canvas)
        sheet = Image.new("RGB", (sum(i.width for i in ims) + 12 * (len(ims) - 1), H + 36), "white")
        x = 0
        for i in ims:
            sheet.paste(i, (x, 0))
            x += i.width + 12
        sheet.save(os.path.join(OUT, "compare", name + ".png"))
        rows.append(f"<h2>{name}</h2><img src='compare/{name}.png' style='max-width:100%'>")
    open(os.path.join(OUT, "index.html"), "w").write(
        "<!doctype html><meta charset=utf-8><title>Netflix visual comparison</title>"
        "<body style='font-family:sans-serif;margin:16px'><h1>Reference vs submitted iterations</h1>"
        f"<p>Not captured (interaction states): {', '.join(NOT_CAPTURED)}</p>" + "".join(rows))


if __name__ == "__main__":
    its = [int(a) for a in sys.argv[1:]] or [1, 5]
    shoot(its)
    compose(its)
    print(os.path.join(OUT, "compare"))
