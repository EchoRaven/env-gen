"""Screenshot my app at 1920x1107 and compare layout/color fingerprints with references."""
import json, sys, urllib.request
from PIL import Image
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3100"
OUT = "/workspace/.local/shots"
W, H = 1920, 1107

def api(method, path, body=None):
    r = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, method=method)
    r.add_header("Content-Type", "application/json")
    if body is None and method == "GET":
        pass
    try:
        with urllib.request.urlopen(r) as resp:
            return json.loads(resp.read().decode() or "null")
    except Exception as e:
        print("api fail", path, e); return None

def fingerprint(img):
    g = img.convert("L")
    w, h = g.size
    px = g.load()
    total, dark, = 0, 0
    rgb = img.convert("RGB")
    rp = rgb.load()
    red = 0
    n = w * h
    # 12x7 luminance grid
    cols, rows = 12, 7
    cw, chh = w / cols, h / rows
    grid = [[0.0] * cols for _ in range(rows)]
    cnt = [[0] * cols for _ in range(rows)]
    for y in range(0, h, 4):
        gy = min(rows - 1, int(y / chh))
        for x in range(0, w, 4):
            gx = min(cols - 1, int(x / cw))
            l = px[x, y]
            grid[gy][gx] += l
            cnt[gy][gx] += 1
            total += l
            if l < 40: dark += 1
            r_, g_, b_ = rp[x, y]
            if r_ > 140 and g_ < 90 and b_ < 90: red += 1
    mean = total / (total and (len(total) or 1)) if False else None
    s = sum(sum(row) for row in grid) / sum(sum(c) for c in cnt)
    mean_l = s
    dark_r = dark / (len(dark) and (dark and 1) or 1) if False else None
    # recount properly with sampling count
    sampled = sum(sum(c) for c in cnt)
    grid = [[grid[y][x] / max(1, cnt[y][x]) for x in range(cols)] for y in range(rows)]
    return {"mean_lum": round(mean_l, 1), "grid": grid,
            "dark_frac": round(dark / max(1, sampled), 3), "red_frac": round(red / max(1, sampled), 4)}

def report(name, mine, ref_path):
    try:
        ref = Image.open(ref_path)
    except Exception as e:
        print(f"{name}: ref load fail {e}"); return
    rf = fingerprint(ref)
    my = mine
    d = [abs(a - b) for arow, brow in zip(my["grid"], rf["grid"]) for a, b in zip(arow, brow)]
    mean_d = sum(d) / len(d)
    worst = sorted(range(len(d)), key=lambda i: -d[i])[:5]
    def cell(i): return f"({i % 12},{i // 12})"
    print(f"{name:28s} mean_lum mine={my['mean_lum']:5.1f} ref={rf['mean_lum']:5.1f} | dark {my['dark_frac']:.2f}/{rf['dark_frac']:.2f} | red {my['red_frac']:.3f}/{rf['red_frac']:.3f} | gridΔ={mean_d:5.1f} worst={[(cell(i), round(d[i],0)) for i in worst]}")

def main():
    demo = api("POST", "/auth/login", {"email": "demo@netflix.example", "password": "demo1234"})
    token, prof_id = demo["access_token"], None
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        pg = b.new_page(viewport={"width": W, "height": H})
        shots = {}
        def shot(name, path=None, wait=1500, pre=None):
            pg.goto(BASE + (path or "/"), wait_until="domcontentloaded")
            if pre: pre()
            pg.wait_for_timeout(wait)
            f = f"{OUT}/{name}.png"
            pg.screenshot(path=f)
            shots[name] = f

        # landing (unauthenticated)
        pg.goto(BASE + "/", wait_until="domcontentloaded")
        pg.wait_for_timeout(1800)
        pg.screenshot(path=f"{OUT}/landing.png"); shots["landing"] = f"{OUT}/landing.png"

        # log in via app storage
        pg.evaluate(f"localStorage.setItem('nf_token', {json.dumps(token)});"
                    f"localStorage.setItem('nf_user', {json.dumps({'id':1,'email':'demo@netflix.example','name':'Demo User'})});"
                    f"localStorage.setItem('nf_profile', '1');")
        shot("browse", "/browse", 2500)
        shot("shows", "/shows", 2500)
        shot("movies", "/movies", 2500)
        shot("games", "/games", 2000)
        shot("new", "/new", 2500)
        shot("genre", "/browse/genre/1", 2500)
        shot("mylist", "/mylist", 2000)
        shot("languages", "/browse/languages", 2000)
        shot("login", "/login", 1500, pre=lambda: pg.evaluate("localStorage.removeItem('nf_token'); localStorage.removeItem('nf_user');"))
        # player
        shot("player", "/watch/2", 3000)
        b.close()

    REF = "/workspace/design/references"
    pairs = [("landing","landing.jpg"),("browse","browse_home.jpg"),("shows","shows.jpg"),
             ("movies","movies.jpg"),("games","games.jpg"),("new","new_and_popular.jpg"),
             ("genre","genre_category.jpg"),("mylist","my_list.jpg"),
             ("languages","browse_by_languages.jpg"),("player","player.jpg"),("login","login.jpg")]
    for name, ref in pairs:
        im = Image.open(shots[name])
        report(name, fingerprint(im), f"{REF}/{ref}")

if __name__ == "__main__":
    main()
