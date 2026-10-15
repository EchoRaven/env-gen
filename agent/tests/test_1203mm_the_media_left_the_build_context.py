r"""#1203mm: 391 MB of video went through the tar, and 83% of runs paid for it.

`#1203ml` measures and names the failure; this removes it. The frontend build context is
393-406 MB of which 391 MB is `public/assets/real_videos`, docker tars the whole context
before the first instruction, and 24 of the 29 modern runs shipping a >100MB media context
hit `archive/tar: missed writing … / unexpected EOF` at least once (0 of 3 without). r189
rebuilt four times and then died with `/assets/real_videos/*.mp4 request_failed` quoted in
its own delivery blocker.

VERIFIED AGAINST THE REAL IMAGE before any of this was written — `tiktok-web-r189-frontend`,
which bakes 71 video files into 490 MB — by running it with a `:ro` mount of a host directory
on `/usr/share/nginx/html/assets/real_videos`:

    /assets/index-J4FiSgga.js     (vite bundle)   200   <- survives the mount
    /assets/index-ijUaYhap.css                    200
    /assets/real_videos/hostonly__clip.mp4        200   <- the MOUNT serves it
    /assets/real_videos/khaby…mp4  (image only)   404   <- so the image does not need it
    /                                             200

That 404 is the proof: what reaches the browser comes from the mount.

★★★ THE OBVIOUS WRITE-UP IS WRONG, and was measured wrong rather than argued: mounting
`public/assets` over `/usr/share/nginx/html/assets` returns **404 for the vite bundle**,
because vite emits `index-<hash>.js` into `dist/assets/` under the same URL prefix. The mount
must name the media SUBDIRECTORY and nothing above it — pinned by
`test_the_mount_never_covers_the_assets_prefix`, the one assertion here that stands between
this patch and a blank app.
"""
import ast
import inspect
import os
import tempfile
import unittest

from env_generator.llm_generator.multi_agent.runtime import validation_runner as VR

MB = 1024 ** 2


def _tree(path, spec):
    """spec: {relative dir: bytes}"""
    for rel, n in spec.items():
        d = os.path.join(path, "public", "assets", rel)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "blob.bin"), "wb") as fh:
            fh.write(b"\0" * n)
    return path


COMPOSE = """name: demo
version: '3.8'

services:
  database:
    image: postgres:16
    volumes:
      - ../app/database/init:/docker-entrypoint-initdb.d:ro
    ports:
      - "8070:8070"

  backend:
    build: ../app/backend
    environment:
      DB_HOST: database

  frontend:
    build: ../app/frontend
    environment:
      UI_PORT: 3000
    ports:
      - "8069:3000"
    depends_on:
      - backend

volumes:
  app_auth_keys:
"""


class ItMeasuresWhichDirectoryIsHeavy(unittest.TestCase):
    def test_only_dirs_past_the_floor_and_biggest_first(self):
        with tempfile.TemporaryDirectory() as t:
            _tree(t, {"real_videos": 150 * MB, "images": 120 * MB, "icons": 2 * MB})
            got = VR.heavy_media_dirs_1203mm(t, floor_mb=100.0)
        self.assertEqual([r for r, _b in got],
                         ["public/assets/real_videos", "public/assets/images"])

    def test_a_small_app_is_untouched(self):
        with tempfile.TemporaryDirectory() as t:
            _tree(t, {"icons": 2 * MB, "fonts": 1 * MB})
            self.assertEqual(VR.heavy_media_dirs_1203mm(t, floor_mb=100.0), [])

    def test_the_directory_name_is_never_assumed(self):
        """r189 stages crops, fonts, icons, images, real_avatars AND real_videos side by
        side, and which one is heavy differs by product."""
        with tempfile.TemporaryDirectory() as t:
            _tree(t, {"clips": 150 * MB, "real_videos": 1 * MB})
            got = VR.heavy_media_dirs_1203mm(t, floor_mb=100.0)
        self.assertEqual([r for r, _b in got], ["public/assets/clips"])

    def test_could_not_tell_is_not_a_verdict(self):
        self.assertEqual(VR.heavy_media_dirs_1203mm("/nonexistent/zzz"), [])
        self.assertEqual(VR.heavy_media_dirs_1203mm(None), [])
        for bad in (object(), 7, []):
            self.assertEqual(VR.heavy_media_dirs_1203mm(bad), [])


class TheMountTargetIsTheThingThatCanKillTheApp(unittest.TestCase):
    def test_the_mount_never_covers_the_assets_prefix(self):
        """MEASURED, not argued: mounting over `/usr/share/nginx/html/assets` 404s the vite
        bundle (`index-<hash>.js` lands in `dist/assets/` too). The mount must end in the
        media subdirectory."""
        out = VR.inject_frontend_volumes_1203mm(COMPOSE, ["public/assets/real_videos"])
        mounts = [l.strip() for l in out.splitlines() if ":/usr/share/nginx/html" in l]
        self.assertTrue(mounts, "no mount was injected")
        for m in mounts:
            target = m.split(":")[1]
            self.assertNotEqual(
                target.rstrip("/"), "/usr/share/nginx/html/assets",
                "the mount covers the whole /assets prefix — this serves a BLANK app, "
                "verified 404 on the vite bundle (#1203mm)")
            self.assertTrue(
                target.startswith("/usr/share/nginx/html/assets/"),
                "the mount target is not inside nginx's assets dir: %r" % target)

    def test_the_target_mirrors_the_url_the_app_requests(self):
        out = VR.inject_frontend_volumes_1203mm(COMPOSE, ["public/assets/real_videos"])
        self.assertIn(
            "- ../app/frontend/public/assets/real_videos:"
            "/usr/share/nginx/html/assets/real_videos:ro", out)

    def test_it_is_read_only(self):
        out = VR.inject_frontend_volumes_1203mm(COMPOSE, ["public/assets/real_videos"])
        for l in out.splitlines():
            if ":/usr/share/nginx/html" in l:
                self.assertTrue(l.rstrip().endswith(":ro"), l)


class TheComposeEditIsNarrow(unittest.TestCase):
    def test_other_services_keep_their_own_volumes(self):
        out = VR.inject_frontend_volumes_1203mm(COMPOSE, ["public/assets/real_videos"])
        self.assertIn("- ../app/database/init:/docker-entrypoint-initdb.d:ro", out)
        self.assertIn("image: postgres:16", out)
        self.assertIn("build: ../app/backend", out)
        self.assertNotIn("nginx", out.split("  backend:")[1].split("  frontend:")[0])

    def test_the_mount_lands_on_the_frontend_service(self):
        out = VR.inject_frontend_volumes_1203mm(COMPOSE, ["public/assets/real_videos"])
        fe = out.split("  frontend:")[1]
        self.assertIn("/usr/share/nginx/html/assets/real_videos", fe)

    def test_load_bearing_comments_survive(self):
        """Text edit, not a YAML round-trip: the generated compose carries comments a dump
        would drop (#1157's name: prepend, FIX #60's env conventions, the vite cache note)."""
        src = "# a load-bearing comment\n" + COMPOSE
        out = VR.inject_frontend_volumes_1203mm(src, ["public/assets/real_videos"])
        self.assertIn("# a load-bearing comment", out)
        self.assertIn("name: demo", out)

    def test_it_is_idempotent(self):
        once = VR.inject_frontend_volumes_1203mm(COMPOSE, ["public/assets/real_videos"])
        twice = VR.inject_frontend_volumes_1203mm(once, ["public/assets/real_videos"])
        self.assertEqual(once, twice)

    def test_an_existing_frontend_volumes_block_is_appended_to(self):
        src = COMPOSE.replace(
            "    build: ../app/frontend\n",
            "    build: ../app/frontend\n    volumes:\n      - ./x:/y:ro\n")
        out = VR.inject_frontend_volumes_1203mm(src, ["public/assets/real_videos"])
        self.assertEqual(out.count("    volumes:\n"), src.count("    volumes:\n"),
                         "a second `volumes:` key was added to the same service")
        self.assertIn("- ./x:/y:ro", out)
        self.assertIn("/usr/share/nginx/html/assets/real_videos", out)

    def test_nothing_to_offload_changes_nothing(self):
        self.assertEqual(VR.inject_frontend_volumes_1203mm(COMPOSE, []), COMPOSE)

    def test_no_frontend_service_is_a_no_op(self):
        src = COMPOSE.replace("  frontend:", "  web:")
        self.assertEqual(
            VR.inject_frontend_volumes_1203mm(src, ["public/assets/real_videos"]), src)


class TheDockerignoreIsAdditive(unittest.TestCase):
    def test_it_adds_the_path_and_says_why(self):
        got = VR.dockerignore_text_1203mm("", ["public/assets/real_videos"])
        self.assertIn("public/assets/real_videos/", got)
        self.assertIn("#1203mm", got)

    def test_existing_entries_survive(self):
        got = VR.dockerignore_text_1203mm("node_modules\ndist\n",
                                          ["public/assets/real_videos"])
        self.assertIn("node_modules", got)
        self.assertIn("dist", got)
        self.assertIn("public/assets/real_videos/", got)

    def test_it_is_idempotent(self):
        once = VR.dockerignore_text_1203mm("", ["public/assets/real_videos"])
        self.assertEqual(VR.dockerignore_text_1203mm(once, ["public/assets/real_videos"]),
                         once)


class EndToEndOnARealShapedTree(unittest.TestCase):
    def _run(self, spec):
        t = tempfile.mkdtemp()
        os.makedirs(os.path.join(t, "docker"))
        with open(os.path.join(t, "docker", "docker-compose.yml"), "w") as fh:
            fh.write(COMPOSE)
        _tree(os.path.join(t, "app", "frontend"), spec)
        cf = os.path.join(t, "docker", "docker-compose.yml")
        got = VR.offload_media_from_build_context_1203mm(cf, floor_mb=100.0)
        return t, cf, got

    def test_the_two_files_agree(self):
        """Anything excluded from the context MUST be mounted back, or the media 404s."""
        t, cf, got = self._run({"real_videos": 150 * MB, "icons": 2 * MB})
        self.assertEqual([r for r, _b in got], ["public/assets/real_videos"])
        di = open(os.path.join(t, "app", "frontend", ".dockerignore")).read()
        compose = open(cf).read()
        for rel, _b in got:
            self.assertIn("%s/" % rel, di, "excluded nothing for %s" % rel)
            self.assertIn("../app/frontend/%s:" % rel, compose,
                          "%s was excluded from the context and never mounted back — the "
                          "app would 404 it" % rel)
        self.assertNotIn("icons", di, "a 2 MB dir was excluded")

    def test_a_second_call_writes_nothing(self):
        t, cf, _ = self._run({"real_videos": 150 * MB})
        before = open(cf).read()
        self.assertEqual(VR.offload_media_from_build_context_1203mm(cf, floor_mb=100.0), [])
        self.assertEqual(open(cf).read(), before)

    def test_a_small_app_gets_no_dockerignore_at_all(self):
        t, cf, got = self._run({"icons": 2 * MB})
        self.assertEqual(got, [])
        self.assertFalse(os.path.exists(os.path.join(t, "app", "frontend", ".dockerignore")))

    def test_it_never_raises(self):
        self.assertEqual(
            VR.offload_media_from_build_context_1203mm("/nonexistent/c/docker-compose.yml"),
            [])
        self.assertEqual(VR.offload_media_from_build_context_1203mm(None), [])


class TheCallSiteRunsBeforeABuild(unittest.TestCase):
    def _compose_fn(self):
        return next((n for n in ast.walk(ast.parse(inspect.getsource(VR)))
                     if isinstance(n, ast.FunctionDef) and n.name == "_compose"), None)

    def test_it_is_called_from_compose(self):
        fn = self._compose_fn()
        self.assertIsNotNone(fn)
        names = {n.func.id for n in ast.walk(fn)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("offload_media_from_build_context_1203mm", names,
                      "defined but never called (#1202w1)")

    def test_it_is_guarded_on_a_building_verb(self):
        """`down`, `logs`, `ps` must not rewrite the project's files."""
        fn = self._compose_fn()
        call = next(n for n in ast.walk(fn)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "offload_media_from_build_context_1203mm")
        guard = None
        for node in ast.walk(fn):
            if isinstance(node, ast.If) and any(
                    c is call for b in node.body for c in ast.walk(b)):
                guard = node
        self.assertIsNotNone(guard, "the #1203mm call is unguarded — it would run on `down`")
        dump = ast.dump(guard.test)
        self.assertIn("'build'", dump)
        self.assertIn("'up'", dump)

    def test_the_call_uses_only_names_compose_binds(self):
        """The #1203ml trap: a NameError here is swallowed by the except below."""
        fn = self._compose_fn()
        bound = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
        if fn.args.vararg:
            bound.add(fn.args.vararg.arg)
        bound |= {t.id for sub in ast.walk(fn) for t in ast.walk(sub)
                  if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store)}
        call = next(n for n in ast.walk(fn)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "offload_media_from_build_context_1203mm")
        free = {t.id for a in call.args for t in ast.walk(a)
                if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Load)}
        self.assertFalse(free - bound, "reads name(s) _compose does not bind: %s"
                         % sorted(free - bound))


if __name__ == "__main__":
    unittest.main()
