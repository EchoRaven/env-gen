"""Interaction-state screenshots vs references (1920x1107)."""
import json, sys, urllib.request
from PIL import Image
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3100"
OUT = "/workspace/.local/shots"
W, H = 1920, 1107

def api(method, path, body=None):
    r = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, method=method)
    r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r) as resp:
            return json.loads(resp.read().decode() or "null")
    except Exception as e:
        print("api fail", path, e); return None

def fingerprint(img):
    g = img.convert("L"); w, h = g.size; px = g.load()
    rgb = img.convert("RGB"); rp = rgb.load()
    cols, rows = 12, 7
    cw, chh = w / cols, h / rows
    grid = [[0.0]*cols for _ in range(rows)]; cnt = [[0]*cols for _ in range(rows)]
    dark = red = sampled = 0
    for y in range(0, h, 4):
        gy = min(rows-1, int(y/chh))
        for x in range(0, w, 4):
            gx = min(cols-1, int(x/cw))
            l = px[x,y]; grid[gy][gx] += l; cnt[gy][gx] += 1; sampled += 1
            if l < 40: dark += 1
            r_,g_,b_ = rp[x,y]
            if r_ > 140 and g_ < 90 and b_ < 90: red += 1
    tot = sum(sum(c) for c in cnt)
    return {"mean": round(sum(sum(r) for r in grid)/tot,1),
            "dark": round(dark/sampled,3), "red": round(red/sampled,4),
            "grid": [[grid[y][x]/max(1,cnt[y][x]) for x in range(cols)] for y in range(rows)]}

def report(name, f1, f2, label1="mine", label2="ref"):
    d = [abs(a-b) for arow,brow in zip(f1["grid"],f2["grid"]) for a,b in zip(arow,brow)]
    md = sum(d)/len(d)
    print(f"{name:24s} {label1}: mean={f1['mean']:5.1f} dark={f1['dark']:.2f} red={f1['red']:.3f} | {label2}: mean={f2['mean']:5.1f} dark={f2['dark']:.2f} red={f2['red']:.3f} | gridD={md:5.1f}")

def main():
    demo = api("POST","/auth/login",{"email":"demo@netflix.example","password":"demo1234"})
    token = demo["access_token"]
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        pg = b.new_page(viewport={"width":W,"height":H})
        def goto(path):
            pg.goto(BASE+path, wait_until="domcontentloaded")
            pg.wait_for_timeout(1800)
        def shot(name):
            pg.screenshot(path=f"{OUT}/{name}.png")
            print("shot", name)
        pg.goto(BASE+"/", wait_until="domcontentloaded"); pg.wait_for_timeout(500)
        pg.evaluate(f"localStorage.setItem('nf_token',{json.dumps(token)});localStorage.setItem('nf_user',{json.dumps({'id':1,'email':'demo@netflix.example','name':'Demo User'})});localStorage.setItem('nf_profile','1');")

        # browse base
        goto("/browse"); pg.wait_for_timeout(1500)
        # title modal
        pg.locator(".card").first.hover(); pg.wait_for_timeout(400)
        pg.locator(".card").first.click(); pg.wait_for_timeout(1500)
        shot("title_detail")
        # episodes view: scroll inside modal
        pg.locator(".modal").evaluate("el => el.scrollTop = 9999")
        pg.locator(".modal").evaluate("el => { const sc = el.querySelector('.modal-body') || el; sc.scrollTop = 9999; }")
        pg.wait_for_timeout(600)
        shot("title_episodes")
        # rate dialog: reopen fresh modal, click thumbs
        pg.keyboard.press("Escape"); pg.wait_for_timeout(500)
        pg.locator(".card").first.click(); pg.wait_for_timeout(1200)
        pg.locator(".modal .round-btn[aria-label='Rate title']").click(); pg.wait_for_timeout(800)
        shot("rate_dialog")
        pg.keyboard.press("Escape"); pg.wait_for_timeout(400)
        pg.keyboard.press("Escape"); pg.wait_for_timeout(800)

        # card hover preview
        pg.locator(".card").nth(2).hover(); pg.wait_for_timeout(700)
        shot("card_hover")
        pg.mouse.move(10, 10); pg.wait_for_timeout(500)

        # account menu
        pg.locator(".profile-menu .icon-btn").click(); pg.wait_for_timeout(600)
        shot("account_menu")
        pg.keyboard.press("Escape"); pg.wait_for_timeout(300)

        # shows + genres menu
        goto("/shows"); pg.wait_for_timeout(1200)
        sel = pg.locator("select.filter-select, select").first
        try:
            sel.click(); pg.wait_for_timeout(500)
        except Exception:
            pass
        shot("shows_genres_menu")
        pg.keyboard.press("Escape")

        # player controls
        goto("/watch/2"); pg.wait_for_timeout(2500)
        try:
            pg.locator("video").dispatch_event("click")
        except Exception: pass
        pg.wait_for_timeout(1500)
        shot("player_controls")
        b.close()

    REF = "/workspace/design/references"
    def ref(name): return fingerprint(Image.open(f"{REF}/{name}"))
    def mine(name): return fingerprint(Image.open(f"{OUT}/{name}.png"))
    pairs = [("title_detail","title_detail.jpg"),("title_episodes","title_episodes.jpg"),
             ("rate_dialog","rate_dialog.jpg"),("card_hover","card_hover_preview.jpg"),
             ("account_menu","account_menu.jpg"),("shows_genres_menu","shows_genres_menu.jpg"),
             ("player_controls","player_controls.jpg")]
    for n, r in pairs:
        try:
            report(n, mine(n), ref(r))
        except Exception as e:
            print(n, "ERR", e)
if __name__ == "__main__":
    main()
