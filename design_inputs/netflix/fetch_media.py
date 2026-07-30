#!/usr/bin/env python3
"""Fetch REAL Netflix-like media for the Netflix env's design_inputs.

Run this in an environment WITH internet (the agent's sandbox has no egress).
It populates, relative to this file's directory:
  dataset/titles.json     — real catalog rows (name, year, genre, rating, runtime, synopsis, poster/backdrop)
  assets/posters/*.jpg     — real poster art          (TMDB)
  assets/backdrops/*.jpg   — real backdrop/hero art    (TMDB)
  assets/video/*.mp4       — royalty-free short clips   (Pexels or Pixabay)
  assets/brand/*.svg       — the real Netflix logo/wordmark (Wikimedia Commons)
  assets/fonts/*.woff2     — FREE Netflix-Sans substitutes (Google Fonts: Anton + Inter)
  assets/icons/*.svg       — real UI icon set          (Lucide, MIT)

Sources & licensing:
  * TMDB  (https://developer.themoviedb.org) — real movie/TV metadata + poster/backdrop images.
  * Pexels (https://www.pexels.com/api/) / Pixabay (https://pixabay.com/api/docs/) — royalty-free video.
  * Wikimedia Commons — the real Netflix logo (trademark: local/research clone use only).
  * Google Fonts (OFL) — free substitutes; Netflix Sans itself is proprietary and NOT fetched.
  * Lucide (MIT) — UI icons.
  We do NOT scrape netflix.com / its CDN (copyright + trademark + ToS).

Run a subset:  python3 fetch_media.py brand           # just logo/font/icons (no keys needed)
               python3 fetch_media.py catalog video   # TMDB + trailers
               python3 fetch_media.py                 # everything

Credentials via env (all free):
  TMDB_TOKEN     v4 read access token  (preferred)  — sent as  Authorization: Bearer <token>
  TMDB_API_KEY   v3 api key            (fallback)   — sent as  ?api_key=<key>
  PEXELS_KEY     Pexels API key        (for video)
  PIXABAY_KEY    Pixabay API key       (for video, fallback)

Usage:
  TMDB_TOKEN=... PEXELS_KEY=... python3 fetch_media.py
  # optional: N_TITLES (default 60), N_VIDEOS (default 6), VIDEO_QUERY (default "cinematic city night")
"""
from __future__ import annotations
import json, os, re, subprocess, sys, time, urllib.parse, urllib.request, urllib.error
from pathlib import Path

# Browser-like UA: Wikimedia Commons / Google Fonts return 403 to blank or generic UAs.
_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

ROOT = Path(__file__).resolve().parent
DATASET = ROOT / "dataset"
POSTERS = ROOT / "assets" / "posters"
BACKDROPS = ROOT / "assets" / "backdrops"
VIDEO = ROOT / "assets" / "video"
LOGO = ROOT / "assets" / "brand"
FONTS = ROOT / "assets" / "fonts"
ICONS = ROOT / "assets" / "icons"

# Netflix brand marks — the REAL logo, legitimately hosted on Wikimedia Commons
# (Special:FilePath redirects to the canonical file). Trademark: local/research clone use.
_BRAND_FILES = {
    "netflix_wordmark.svg": "https://commons.wikimedia.org/wiki/Special:FilePath/Netflix_2015_logo.svg",
    "netflix_n_icon.svg":   "https://commons.wikimedia.org/wiki/Special:FilePath/Netflix_icon.svg",
}
# Netflix Sans is proprietary; these are FREE (OFL) look-alikes: Bebas Neue-ish display + Inter UI.
_GOOGLE_FONTS = {
    "display": "Anton",   # heavy condensed display, close to Netflix Sans headings
    "ui": "Inter",        # neutral UI face
}
# Real UI icon set the generated React app uses anyway (Lucide, MIT).
_LUCIDE_ICONS = [
    "play", "pause", "plus", "check", "thumbs-up", "thumbs-down", "chevron-down",
    "chevron-left", "chevron-right", "search", "bell", "volume-2", "volume-x",
    "maximize", "x", "info", "download",
]

TMDB_TOKEN = os.environ.get("TMDB_TOKEN", "").strip()
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "").strip()
PEXELS_KEY = os.environ.get("PEXELS_KEY", "").strip()
PIXABAY_KEY = os.environ.get("PIXABAY_KEY", "").strip()
N_TITLES = int(os.environ.get("N_TITLES", "60"))
N_VIDEOS = int(os.environ.get("N_VIDEOS", "6"))
VIDEO_QUERY = os.environ.get("VIDEO_QUERY", "cinematic city night")

IMG_BASE = "https://image.tmdb.org/t/p"


def _curl(url: str, headers: dict, timeout: int):
    """Fetch via curl — passes Cloudflare/proxy setups urllib's client signature can't
    (e.g. Pexels' CF error 1010). Returns bytes on success, else None."""
    cmd = ["curl", "-fsSL", "--max-time", str(timeout)]
    ua = _UA
    for k, v in (headers or {}).items():
        if k.lower() == "user-agent":
            ua = v
        else:
            cmd += ["-H", f"{k}: {v}"]
    cmd += ["-A", ua, url]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=timeout + 15)
    except Exception:
        return None
    return out.stdout if (out.returncode == 0 and out.stdout) else None


def _get(url: str, headers: dict | None = None, binary: bool = False, timeout: int = 30):
    hdrs = headers or {"User-Agent": _UA}
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
    except Exception as e:
        data = _curl(url, hdrs, timeout)  # fallback: curl reaches hosts urllib can't
        if not data:
            if isinstance(e, urllib.error.HTTPError):
                body = ""
                try:
                    body = e.read().decode("utf-8", "ignore")[:300]
                except Exception:
                    pass
                raise RuntimeError(f"HTTP {e.code} for {url} :: {body}") from None
            raise RuntimeError(f"{type(e).__name__} for {url}: {str(e)[:200]}") from None
    return data if binary else json.loads(data.decode("utf-8"))


def _tmdb(path: str, **params):
    """Call the TMDB v3 API using either the v4 bearer token or the v3 api_key."""
    headers = {"User-Agent": _UA, "accept": "application/json"}
    if TMDB_TOKEN:
        headers["Authorization"] = f"Bearer {TMDB_TOKEN}"
    elif TMDB_API_KEY:
        params["api_key"] = TMDB_API_KEY
    else:
        raise SystemExit("Set TMDB_TOKEN (v4) or TMDB_API_KEY (v3).")
    qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    return _get(f"https://api.themoviedb.org/3/{path}?{qs}", headers=headers)


def _download(url: str, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 0:
        return True
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(_get(url, binary=True))
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  ! download failed {url}: {e}", file=sys.stderr)
        return False


def fetch_catalog() -> None:
    print(f"[TMDB] genre maps + up to {N_TITLES} titles ...")
    gm = {g["id"]: g["name"] for g in _tmdb("genre/movie/list").get("genres", [])}
    gt = {g["id"]: g["name"] for g in _tmdb("genre/tv/list").get("genres", [])}
    seen, rows = set(), []
    # a spread of rails so the catalog looks like Netflix's mixed home
    feeds = [
        ("movie", "trending/movie/week"), ("tv", "trending/tv/week"),
        ("movie", "movie/popular"), ("tv", "tv/popular"),
        ("movie", "movie/top_rated"), ("tv", "tv/top_rated"),
    ]
    for kind, path in feeds:
        if len(rows) >= N_TITLES:
            break
        try:
            results = _tmdb(path).get("results", [])
        except Exception as e:  # noqa: BLE001
            print(f"  ! {path}: {e}", file=sys.stderr)
            continue
        gmap = gm if kind == "movie" else gt
        for it in results:
            if len(rows) >= N_TITLES:
                break
            tid = f"{kind}:{it.get('id')}"
            if tid in seen or not it.get("poster_path"):
                continue
            seen.add(tid)
            name = it.get("title") or it.get("name") or "Untitled"
            date = it.get("release_date") or it.get("first_air_date") or ""
            genres = [gmap.get(g, "") for g in (it.get("genre_ids") or [])]
            genres = [g for g in genres if g]
            stem = f"{kind}_{it.get('id')}"
            poster_rel = f"posters/{stem}.jpg"
            backdrop_rel = f"backdrops/{stem}.jpg" if it.get("backdrop_path") else None
            _download(f"{IMG_BASE}/w500{it['poster_path']}", ROOT / "assets" / poster_rel)
            if it.get("backdrop_path"):
                _download(f"{IMG_BASE}/w1280{it['backdrop_path']}", ROOT / "assets" / backdrop_rel)
            rows.append({
                "id": len(rows) + 1,
                "kind": "movie" if kind == "movie" else "series",
                "name": name,
                "year": (date[:4] or None),
                "genre": (genres[0] if genres else None),
                "genres": genres,
                "maturity_rating": ("TV-MA" if it.get("adult") else "TV-14"),
                "rating": round(float(it.get("vote_average") or 0), 1),
                "synopsis": (it.get("overview") or "").strip(),
                "poster": f"assets/{poster_rel}",
                "backdrop": (f"assets/{backdrop_rel}" if backdrop_rel else None),
                "language": it.get("original_language"),
            })
        time.sleep(0.2)
    DATASET.mkdir(parents=True, exist_ok=True)
    (DATASET / "titles.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[TMDB] wrote {len(rows)} rows -> {DATASET/'titles.json'}; "
          f"{len(list(POSTERS.glob('*.jpg')))} posters, {len(list(BACKDROPS.glob('*.jpg')))} backdrops")


def fetch_videos() -> None:
    VIDEO.mkdir(parents=True, exist_ok=True)
    if PEXELS_KEY:
        print(f"[Pexels] {N_VIDEOS} clips for '{VIDEO_QUERY}' ...")
        q = urllib.parse.urlencode({"query": VIDEO_QUERY, "per_page": N_VIDEOS, "orientation": "landscape"})
        data = _get(f"https://api.pexels.com/videos/search?{q}", headers={"Authorization": PEXELS_KEY})
        for v in data.get("videos", [])[:N_VIDEOS]:
            files = sorted(v.get("video_files", []), key=lambda f: (f.get("width") or 0))
            hd = [f for f in files if 640 <= (f.get("width") or 0) <= 1280] or files
            if hd:
                _download(hd[0]["link"], VIDEO / f"clip_{v['id']}.mp4")
    elif PIXABAY_KEY:
        print(f"[Pixabay] {N_VIDEOS} clips for '{VIDEO_QUERY}' ...")
        q = urllib.parse.urlencode({"key": PIXABAY_KEY, "q": VIDEO_QUERY, "per_page": max(3, N_VIDEOS)})
        data = _get(f"https://pixabay.com/api/videos/?{q}")
        for h in data.get("hits", [])[:N_VIDEOS]:
            url = (h.get("videos", {}).get("medium") or h.get("videos", {}).get("small") or {}).get("url")
            if url:
                _download(url, VIDEO / f"clip_{h.get('id')}.mp4")
    else:
        print("[video] no PEXELS_KEY / PIXABAY_KEY set — skipping trailers", file=sys.stderr)
        return
    print(f"[video] {len(list(VIDEO.glob('*.mp4')))} clips -> {VIDEO}")


def fetch_brand() -> None:
    """Real Netflix logo (Wikimedia), a free Netflix-Sans substitute font, and the Lucide icon set."""
    print("[brand] Netflix logo (Wikimedia Commons) ...")
    for name, url in _BRAND_FILES.items():
        _download(url, LOGO / name)
    print(f"[brand] {len(list(LOGO.glob('*.svg')))} logo file(s) -> {LOGO}")

    print("[font] free Netflix-Sans substitutes (Google Fonts, OFL) ...")
    FONTS.mkdir(parents=True, exist_ok=True)
    for role, fam in _GOOGLE_FONTS.items():
        got = 0
        # try a multi-weight spec, then fall back to the family's default axis (single-weight
        # display faces like Anton 400-only reject wght@700;900 with a 400).
        for spec in (f"{fam}:wght@400;700", fam):
            try:
                css_url = ("https://fonts.googleapis.com/css2?family="
                           + urllib.parse.quote(spec) + "&display=swap")
                css = _get(css_url, headers={"User-Agent": _UA}, binary=True).decode("utf-8", "ignore")
                for i, u in enumerate(dict.fromkeys(re.findall(r"url\((https://[^)]+\.woff2)\)", css))):
                    if _download(u, FONTS / f"{role}_{fam.lower()}_{i}.woff2"):
                        got += 1
                if got:
                    break
            except Exception as e:  # noqa: BLE001
                print(f"  ! font {fam} [{spec}]: {e}", file=sys.stderr)
    print(f"[font] {len(list(FONTS.glob('*.woff2')))} woff2 -> {FONTS}")

    print(f"[icons] Lucide set ({len(_LUCIDE_ICONS)}) ...")
    for ic in _LUCIDE_ICONS:
        _download(f"https://unpkg.com/lucide-static@latest/icons/{ic}.svg", ICONS / f"{ic}.svg")
    print(f"[icons] {len(list(ICONS.glob('*.svg')))} svg -> {ICONS}")


if __name__ == "__main__":
    what = set(sys.argv[1:]) or {"catalog", "video", "brand"}
    # Each stage is isolated: a failure (e.g. one host 403) prints the exact URL+status+body
    # and the other stages still run.
    if "catalog" in what:
        if TMDB_TOKEN or TMDB_API_KEY:
            try:
                fetch_catalog()
            except Exception as e:  # noqa: BLE001
                print("[catalog] FAILED:", e, file=sys.stderr)
        else:
            print("[TMDB] no token — skipping catalog", file=sys.stderr)
    if "video" in what:
        try:
            fetch_videos()
        except Exception as e:  # noqa: BLE001
            print("[video] FAILED:", e, file=sys.stderr)
    if "brand" in what:
        try:
            fetch_brand()
        except Exception as e:  # noqa: BLE001
            print("[brand] FAILED:", e, file=sys.stderr)
    print("done.")
