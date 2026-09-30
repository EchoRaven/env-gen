"""Is there room for a run, and if not, WHERE is the space actually reclaimable?

The launcher's disk preflight has refused with the same sentence for weeks —
`先 docker builder prune -af`. On 2026-09-29 that advice reclaims **nothing**: build cache is
0B, while 39.06GB sits in images and 20.82GB in volumes. A hint that was true once sends the
reader to the one place with nothing in it, and root is at EXACTLY the 60G floor (97% full),
so this message is about to be read.

So it measures instead of hinting, and it separates the two kinds of reclaimable space,
because they are not equally safe:

  * **dangling IMAGES are safe** — untagged, referenced by no container, and rebuildable.
  * **dangling VOLUMES are DATA.** `docker volume ls -f dangling=true` means "referenced by no
    container", which INCLUDES an environment that is merely STOPPED and whose data matters.
    On this machine that set covers other work lines' environments (windows_web, macos_web and
    the messaging apps), so it is never a safe blanket prune.

    python scripts/disk_headroom.py [floor_gb]     # default 60, exit 1 when below
"""
import re
import shutil
import subprocess
import sys


def _docker_df():
    """{type: (size_bytes_text, reclaimable_text)} or {} when docker cannot be read."""
    try:
        out = subprocess.run(["docker", "system", "df"], capture_output=True, text=True,
                             timeout=30).stdout
    except Exception:
        return {}
    rows = {}
    for line in out.splitlines()[1:]:
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) >= 5:
            rows[parts[0]] = (parts[3], parts[4])
    return rows


def _gb(text: str) -> float:
    m = re.match(r"([\d.]+)\s*([KMGT]?)B", str(text).strip(), re.I)
    if not m:
        return 0.0
    n = float(m.group(1))
    return n * {"": 1e-9, "K": 1e-6, "M": 1e-3, "G": 1.0, "T": 1000.0}[m.group(2).upper()]


def report(floor_gb: int = 60):
    # EXACT bytes, not `df -BG`. The launcher tested `df --output=avail -BG` >= 60, and
    # `df -BG` rounds UP: at 59.625 GiB free it printed 60G and the check PASSED, so the
    # floor was really 59.001 GiB. A floor that rounds toward ADMITTING is the wrong
    # direction — it lets in the run that dies at minute 40 with a full disk, which is the
    # failure the floor exists to prevent.
    avail = shutil.disk_usage("/").free / (1024 ** 3)
    ok = avail >= floor_gb
    lines = ["[disk] root has %.2fG free (exact); the floor is %dG -> %s"
             % (avail, floor_gb, "OK" if ok else "REFUSED")]
    df = _docker_df()
    if not df:
        lines.append("[disk] docker could not be read, so no reclaim advice — check by hand")
        return (0 if ok else 1), "\n".join(lines)
    img = _gb((df.get("Images") or ("", "0B"))[1])
    vol = _gb((df.get("Local Volumes") or ("", "0B"))[1])
    cache = _gb((df.get("Build Cache") or ("", "0B"))[1])
    lines.append("[disk] reclaimable NOW: images %.1fG · volumes %.1fG · build cache %.1fG"
                 % (img, vol, cache))
    # Ordered by what is both large and safe, measured — not by what used to be true.
    advice = []
    if img >= 1.0:
        advice.append("docker image prune          # %.1fG, SAFE: untagged, unreferenced, "
                      "rebuildable" % img)
    if cache >= 1.0:
        advice.append("docker builder prune -af    # %.1fG" % cache)
    elif not ok:
        advice.append("(build cache holds %.1fG — the old advice to prune it reclaims "
                      "nothing)" % cache)
    if vol >= 1.0:
        advice.append("docker volume prune         # %.1fG, *** NOT SAFE ***: 'dangling' "
                      "includes STOPPED environments whose data matters, other work lines "
                      "included. Decide per volume." % vol)
    if advice:
        lines.append("[disk] " + "\n[disk] ".join(advice))
    return (0 if ok else 1), "\n".join(lines)


def main(argv):
    floor = 60
    if len(argv) > 1:
        try:
            floor = int(argv[1])
        except ValueError:
            pass
    code, msg = report(floor)
    print(msg)
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
