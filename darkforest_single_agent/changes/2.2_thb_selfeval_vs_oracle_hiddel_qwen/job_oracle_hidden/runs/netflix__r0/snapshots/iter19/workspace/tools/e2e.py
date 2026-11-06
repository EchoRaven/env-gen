"""Headless E2E: landing -> login -> profiles -> browse -> modal -> my list -> player -> nav."""
import sys, time
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:3100"
fails = []
passes = []

def check(name, cond, extra=""):
    (passes if cond else fails).append(name)
    print(("PASS " if cond else "FAIL ") + name + (" " + str(extra) if not cond else ""))

with sync_playwright() as pw:
    browser = pw.chromium.launch(args=["--no-sandbox", "--use-gl=swiftshader"])
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))

    # 1. Landing
    page.goto(BASE + "/", wait_until="networkidle")
    check("landing wordmark", page.locator("img[alt='NETFLIX']").count() > 0)
    check("landing has email input", page.locator("input[type=email]").count() > 0)
    check("landing posters", page.locator(".collage-grid img").count() >= 10)

    # 2. Get started -> login
    page.locator("input[type=email]").fill("demo@netflix.example")
    page.locator(".landing-email-row button").click()
    page.wait_for_url("**/login**", timeout=5000)
    h1 = page.inner_text("h1")
    check("login page shown", "Sign In" in h1 or "Sign Up" in h1, h1)
    # Get Started opened signup mode; switch to sign-in
    if "Sign Up" in h1:
        page.locator(".login-card .alt a").click()
        page.wait_for_timeout(300)

    # 3. Sign in as demo user
    page.locator(".login-card input[type=email]").fill("demo@netflix.example")
    page.locator(".login-card input[type=password]").first.fill("demo1234")
    page.locator(".btn-signin").click()
    page.wait_for_url("**/profiles", timeout=8000)
    check("profiles page shown", "Who’s watching?" in page.inner_text("body") or "Who's watching?" in page.inner_text("body"))
    picks = page.locator(".profiles-grid .profile-pick")
    check("3 profile tiles + add", picks.count() == 4, picks.count())

    # 4. Select first profile
    picks.first.click()
    page.wait_for_url("**/browse", timeout=8000)
    page.wait_for_timeout(1500)
    check("hero title present", page.locator(".hero-title").count() > 0)
    rails = page.locator(".rail")
    check("rails present", rails.count() >= 6, rails.count())
    posters = page.locator(".card img.card-poster")
    check("posters present", posters.count() >= 20, posters.count())

    # 5. Continue watching rail populated (demo seed)
    cw = page.locator(".rail", has_text="Continue Watching").locator(".card")
    check("continue watching seeded", cw.count() >= 3, cw.count())

    # 6. Open title modal via first card
    posters.first.click()
    page.wait_for_selector(".modal", timeout=5000)
    check("modal opened", page.locator(".modal-title").count() > 0)
    check("modal has play", page.locator(".modal-actions .btn-play").count() > 0)
    # add to list from modal
    modal_plus = page.locator(".modal-actions .round-btn").first
    modal_plus.click()
    page.wait_for_timeout(600)
    # remove again (toggles)
    modal_plus.click()
    page.wait_for_timeout(600)
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)

    # 7. Play from modal
    page.locator(".card").first.click()
    page.wait_for_selector(".modal", timeout=5000)
    page.locator(".modal-actions .btn-play").click()
    page.wait_for_url("**/watch/**", timeout=8000)
    page.wait_for_timeout(2500)
    vid = page.locator("video")
    check("player video element", vid.count() > 0)
    check("player controls visible", page.locator(".player-controls").count() > 0)
    # play/pause button toggles
    btn = page.locator(".player-btn-row .pbtn").first
    btn.click(); page.wait_for_timeout(400)
    btn.click(); page.wait_for_timeout(400)
    # seek fill present
    check("seek bar present", page.locator(".seek-fill").count() > 0)
    # subtitles menu
    page.locator(".player-right .pbtn").nth(1).click()
    page.wait_for_timeout(300)
    check("subs menu opens", page.locator(".player-menu").count() > 0)
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    # back
    page.locator(".player-back").click()
    page.wait_for_timeout(1200)

    # 8. My List page (demo user has 4 seeded)
    page.locator(".nf-nav a", has_text="My List").click()
    page.wait_for_url("**/mylist", timeout=6000)
    page.wait_for_timeout(1000)
    grid = page.locator(".poster-grid .grid-card")
    n0 = grid.count()
    check("my list has items", n0 >= 3, n0)
    # remove first
    page.locator(".grid-remove").first.click()
    page.wait_for_timeout(800)
    n1 = page.locator(".poster-grid .grid-card").count()
    check("my list removed one", n1 == n0 - 1, f"{n0} -> {n1}")

    # 9. Shows / Movies / Games / New
    page.locator(".nf-nav a", has_text="Shows").click()
    page.wait_for_timeout(1200)
    check("shows page rails", page.locator(".rail").count() >= 3)
    page.locator(".nf-nav a", has_text="Movies").click()
    page.wait_for_timeout(1200)
    check("movies page rails", page.locator(".rail").count() >= 3)
    page.locator(".nf-nav a", has_text="Games").click()
    page.wait_for_timeout(1200)
    check("games page empty rails", page.locator(".rail-empty").count() >= 3)
    page.locator(".nf-nav a", has_text="New & Popular").click()
    page.wait_for_timeout(1200)
    check("top10 cards", page.locator(".top10-card").count() >= 10, page.locator(".top10-card").count())
    check("coming this week", page.locator(".new-card").count() >= 1)

    # 10. Languages
    page.locator(".nf-nav a", has_text="Browse by Languages").click()
    page.wait_for_timeout(1200)
    check("lang panels", page.locator(".lang-panel").count() == 3)
    page.locator(".lang-panel select").first.select_option("ja")
    page.wait_for_timeout(600)
    cards = page.locator(".poster-grid .grid-card")
    check("language filter changes grid", 0 < cards.count() < 20, cards.count())

    # 11. Genre dropdown on Shows
    page.locator(".nf-nav a", has_text="Shows").click()
    page.wait_for_timeout(1000)
    opts = page.locator(".filter-select option")
    check("genre options exist", opts.count() >= 5, opts.count())
    page.locator(".filter-select").select_option(index=1)
    page.wait_for_url("**/browse/genre/**", timeout=6000)
    page.wait_for_timeout(1000)
    check("genre page renders", page.locator(".rail").count() >= 1)

    # 12. Search
    page.locator(".nf-header-right .icon-btn").first.click()
    page.wait_for_timeout(400)
    page.locator(".search-input").fill("the")
    page.wait_for_timeout(900)
    check("search results dropdown", page.locator(".search-result-row").count() >= 1)
    page.keyboard.press("Enter")
    page.wait_for_url("**/search**", timeout=6000)
    page.wait_for_selector(".poster-grid .grid-card", timeout=6000)
    check("search page grid", page.locator(".poster-grid .grid-card").count() >= 1)

    # 13. Account menu + profile menu
    page.locator(".profile-menu .icon-btn").click()
    page.wait_for_timeout(300)
    check("account menu opens", page.locator(".dropdown-item").count() >= 3)
    page.locator(".dropdown-item", has_text="Account").click()
    page.wait_for_url("**/account", timeout=6000)
    check("account page", "Membership" in page.inner_text("body"))

    # 14. Sign out
    page.locator(".profile-menu .icon-btn").click()
    page.wait_for_timeout(300)
    page.locator(".dropdown-item", has_text="Sign out").click()
    page.wait_for_url("**/**", timeout=6000)
    page.wait_for_timeout(800)
    check("signed out -> landing", page.locator(".landing").count() > 0)

    real_errors = [e for e in errors if "favicon" not in e.lower() and "404" not in e]
    check("no console errors", len(real_errors) == 0, real_errors[:5])
    browser.close()

print()
print(f"E2E PASSED: {len(passes)}  FAILED: {len(fails)}")
if fails:
    print("Failures:", fails)
    sys.exit(1)
