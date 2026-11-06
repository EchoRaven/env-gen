"""Local dev seeding for SQLite (mirrors tools/gen_seed.py). Run: python tools/local_seed.py"""
import os
import sys
sys.path.insert(0, "/workspace/app/backend")
os.environ["DATABASE_URL"] = "sqlite:////workspace/.local/test.db"

from app.database import Base, engine, SessionLocal
from app import models

# reset
Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)

import json
CLIPS = ["clip_18972999","clip_27152549","clip_27152555","clip_30070091","clip_30997958","clip_35079542"]
EP_NAMES = ["Pilot","The Arrival","Under Current","A Quiet Line","Signal Lost","The Long Road","Paper Walls",
            "Night Crossing","The Counterfeit","Static","Second Wind","The Archive","Broken Compass","Half Light",
            "The Undertow","Falling Forward","The Exchange","Cold Storage","The Periphery","Ember","The Cartographer",
            "Last Light","The Reckoning","Whiteout","The Inheritance","Crossing Point","The Ledger","Ashes of Us",
            "The Verge","Homecoming Wire","The Threshold","Final Coordinate"]

db = SessionLocal()
db.query(models.User).delete()
db.query(models.Profile).delete()
db.query(models.Genre).delete()
db.query(models.Title).delete()
db.query(models.Episode).delete()
db.query(models.TitleGenre).delete()
db.query(models.MyList).delete()
db.query(models.Rating).delete()
db.query(models.ContinueWatching).delete()
db.commit()

titles = json.load(open("/workspace/app/dataset/titles.json"))

from app.security import hash_password
u = models.User(id=1, email="demo@netflix.example", password_hash=hash_password("demo1234"), name="Demo User")
db.add(u); db.commit()

profiles = [models.Profile(id=1, user_id=1, name="Alex", avatar="avatar_0"),
            models.Profile(id=2, user_id=1, name="Priya", avatar="avatar_1"),
            models.Profile(id=3, user_id=1, name="Kids", avatar="avatar_2", is_kids=True)]
db.add_all(profiles); db.commit()

genre_names = []
for t in titles:
    for g in (t.get("genres") or []):
        if g and g not in genre_names:
            genre_names.append(g)
genres = {name: models.Genre(id=i+1, name=name) for i, name in enumerate(genre_names)}
db.add_all(genres.values()); db.commit()

by_kind = {}
for t in titles:
    by_kind.setdefault(t["kind"], []).append(t)
rank_map = {}
for kind, group in by_kind.items():
    for rank, t in enumerate(sorted(group, key=lambda x: (-x["rating"], x["id"]))[:10], 1):
        rank_map[t["id"]] = rank

for t in titles:
    tid = t["id"]
    backdrop = t.get("backdrop")
    if not backdrop or not os.path.exists(os.path.join("/workspace/design", backdrop)):
        backdrop = t.get("poster")
    dur = (88 + (tid*7) % 68) if t["kind"] == "movie" else (40 + (tid*5) % 18)
    db.add(models.Title(id=tid, name=t["name"], kind=t["kind"], year=t["year"], genre=t.get("genre"),
                        maturity_rating=t.get("maturity_rating"), rating=t.get("rating"), synopsis=t.get("synopsis"),
                        language=t.get("language"), poster=t.get("poster"), backdrop=backdrop,
                        video_url="/media/video/%s.mp4" % CLIPS[tid % len(CLIPS)],
                        duration=dur*60, top10_rank=rank_map.get(tid)))
    for g in (t.get("genres") or []):
        if g in genres:
            db.add(models.TitleGenre(title_id=tid, genre_id=genres[g].id))
    if t["kind"] == "series":
        seasons = 2 + (tid % 3)
        for s in range(1, seasons+1):
            eps = 6 + (tid + s) % 3
            for n in range(1, eps+1):
                db.add(models.Episode(title_id=tid, season=s, number=n,
                                      name=EP_NAMES[(tid*3 + s*5 + n) % len(EP_NAMES)],
                                      synopsis=t.get("synopsis"),
                                      duration=1800 + (tid*13 + s*7 + n*11) % 2100,
                                      thumbnail=backdrop or t.get("poster")))

for pid, tid in [(1,3),(1,7),(1,11),(1,14),(2,2),(2,9)]:
    db.add(models.MyList(profile_id=pid, title_id=tid))
for pid, tid, v in [(1,2,3),(1,5,2),(1,8,1),(2,4,2)]:
    db.add(models.Rating(profile_id=pid, title_id=tid, value=v))
for pid, tid, p in [(1,2,28),(1,5,41),(1,8,12),(2,4,33)]:
    db.add(models.ContinueWatching(profile_id=pid, title_id=tid, progress_seconds=p))
db.commit()
db.close()
print("seeded local sqlite db")
