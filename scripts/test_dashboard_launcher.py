#!/usr/bin/env python3
"""Tests for the Docker-preferred / python-fallback dashboard launcher.

Standard library ``unittest`` only, and NO live Docker daemon: every pure
function is exercised with plain data, and the side-effect shell is driven
through a recording ``mock.patch("dashboard_launcher.subprocess.run")`` so the
exact argv sequences (and their security invariants) are asserted without ever
touching docker. Mirrors the argv-recording + shell-free patterns in
``test_pr_resolver.py``.

Covers TDD steps 1-8 from docs/superpowers/plans/2026-06-30-s3.md:
  1. constants (DEFAULT_PORT mirrored) + parse_daemon_available/fallback.
  2. registry read/write round-trip + prune_stale (both drop reasons).
  3. desired_roots union/sort/realpath-dedup.
  4. mount composition (the architect BLOCKER fix).
  5. build_run_argv SECURITY asserts.
  6. build_stop_argv / build_rm_argv scoped to SINGLETON_NAME only.
  7. ps/image parsers + plan_launch (REUSE/RECREATE/CREATE/BUILD/FALLBACK).
  8. main() dispatch via injected fake runner (name-conflict, port-bound,
     docker-absent fallback).

Usage:
    python3 scripts/test_dashboard_launcher.py
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dashboard_launcher as dl  # noqa: E402
import dashboard_server as ds  # noqa: E402


def _proc(returncode=0, stdout="", stderr=""):
    """A stand-in for a subprocess.CompletedProcess."""
    return mock.Mock(returncode=returncode, stdout=stdout, stderr=stderr)


# --------------------------------------------------------------------------
# Step 1 — constants + daemon predicate + fallback decision
# --------------------------------------------------------------------------

class TestConstantsAndDaemon(unittest.TestCase):
    def test_default_port_mirrors_server_source_of_truth(self):
        # Imported, not re-declared as an independent literal.
        self.assertEqual(dl.DEFAULT_PORT, ds.DEFAULT_PORT)

    def test_singleton_and_image_constants(self):
        self.assertEqual(dl.SINGLETON_NAME, "spec-loop-dashboard")
        self.assertEqual(dl.IMAGE_TAG, "spec-loop-dashboard:local")

    def test_state_dir_is_expanded(self):
        self.assertNotIn("~", dl.STATE_DIR)
        self.assertTrue(dl.STATE_DIR.endswith(os.path.join("dashboard")))

    def test_stale_seconds_is_a_named_positive_cutoff(self):
        self.assertIsInstance(dl.STALE_SECONDS, int)
        self.assertGreater(dl.STALE_SECONDS, 0)

    def test_daemon_available_only_on_rc_zero(self):
        self.assertTrue(dl.parse_daemon_available(0))
        self.assertFalse(dl.parse_daemon_available(1))
        self.assertFalse(dl.parse_daemon_available(125))

    def test_image_present_predicate(self):
        self.assertTrue(dl.parse_image_present("sha256:abc\n"))
        self.assertFalse(dl.parse_image_present(""))
        self.assertFalse(dl.parse_image_present("   \n"))


# --------------------------------------------------------------------------
# Step 2 — registry read/write + prune_stale
# --------------------------------------------------------------------------

class TestRegistry(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self._tmp.name, "state")

    def tearDown(self):
        self._tmp.cleanup()

    def test_absent_registry_is_empty_never_crashes(self):
        self.assertEqual(dl.read_registry(self.state), {})

    def test_corrupt_registry_is_empty_never_crashes(self):
        os.makedirs(self.state)
        with open(os.path.join(self.state, dl.REGISTRY_NAME), "w") as fh:
            fh.write("{ this is not json ]")
        self.assertEqual(dl.read_registry(self.state), {})

    def test_non_dict_payload_degrades_to_empty(self):
        os.makedirs(self.state)
        with open(os.path.join(self.state, dl.REGISTRY_NAME), "w") as fh:
            json.dump([1, 2, 3], fh)
        self.assertEqual(dl.read_registry(self.state), {})

    def test_write_then_read_round_trip_creates_dir(self):
        root = self._tmp.name  # a real, existing dir
        dl.write_root_entry(self.state, root, 1000.0)
        reg = dl.read_registry(self.state)
        self.assertEqual(reg[os.path.realpath(root)], 1000.0)

    def test_write_is_keyed_by_realpath(self):
        # Two spellings of the same dir collapse to one realpath key.
        root = self._tmp.name
        dl_write = dl.write_root_entry
        dl_write(self.state, root, 1.0)
        dl_write(self.state, root + os.sep + ".", 2.0)
        reg = dl.read_registry(self.state)
        self.assertEqual(list(reg.keys()), [os.path.realpath(root)])
        self.assertEqual(reg[os.path.realpath(root)], 2.0)


class TestPruneStale(unittest.TestCase):
    def test_drops_entries_older_than_cutoff(self):
        now, cutoff = 10_000.0, 100.0
        reg = {"/fresh": 9_950.0, "/stale": 9_800.0}
        survivors = dl.prune_stale(reg, now, cutoff, path_exists=lambda p: True)
        self.assertEqual(set(survivors), {"/fresh"})

    def test_drops_entries_whose_artifact_dir_is_gone(self):
        now, cutoff = 10_000.0, 100.0
        reg = {"/present": 9_990.0, "/missing": 9_990.0}
        exists = lambda p: p == os.path.join("/present", dl.DATA_REL)
        survivors = dl.prune_stale(reg, now, cutoff, path_exists=exists)
        self.assertEqual(set(survivors), {"/present"})

    def test_both_drop_reasons_are_independent(self):
        now, cutoff = 10_000.0, 100.0
        reg = {
            "/keep": 9_990.0,         # fresh + present
            "/old": 9_000.0,          # stale (drop by age)
            "/gone": 9_990.0,         # fresh but missing (drop by path)
        }
        exists = lambda p: not p.startswith("/gone")
        survivors = dl.prune_stale(reg, now, cutoff, path_exists=exists)
        self.assertEqual(set(survivors), {"/keep"})

    def test_path_check_targets_the_artifact_subdir(self):
        seen = []
        dl.prune_stale({"/r": 5.0}, 5.0, 10.0,
                       path_exists=lambda p: seen.append(p) or True)
        self.assertEqual(seen, [os.path.join("/r", dl.DATA_REL)])
        self.assertTrue(seen[0].endswith(os.path.join("docs", "spec-loop")))


# --------------------------------------------------------------------------
# Step 3 — desired_roots union / sort / realpath-dedup
# --------------------------------------------------------------------------

class TestDesiredRoots(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def test_sorted_deduped_survivors(self):
        base = self._tmp.name
        a = os.path.join(base, "a")
        b = os.path.join(base, "b")
        for d in (a, b):
            os.makedirs(os.path.join(d, dl.DATA_REL))
        reg = {b: 100.0, a: 100.0}
        roots = dl.desired_roots(reg, 100.0, 1000.0, os.path.exists)
        self.assertEqual(roots, sorted([os.path.realpath(a),
                                        os.path.realpath(b)]))

    def test_same_root_two_spellings_dedups_by_realpath(self):
        base = self._tmp.name
        a = os.path.join(base, "a")
        os.makedirs(os.path.join(a, dl.DATA_REL))
        reg = {a: 100.0, os.path.join(a, "."): 100.0}
        roots = dl.desired_roots(reg, 100.0, 1000.0, os.path.exists)
        self.assertEqual(roots, [os.path.realpath(a)])


# --------------------------------------------------------------------------
# Step 4 — mount composition (the architect BLOCKER fix)
# --------------------------------------------------------------------------

class TestMountComposition(unittest.TestCase):
    def test_mount_point_is_the_container_root_not_the_target(self):
        # The value passed to --root; the server appends docs/spec-loop to it.
        self.assertEqual(dl.mount_point_for("repo"), "/roots/repo")

    def test_source_is_host_artifact_dir(self):
        src = dl.mount_source_for("/home/me/proj")
        self.assertEqual(src, os.path.join("/home/me/proj", dl.DATA_REL))
        self.assertTrue(src.endswith(os.path.join("docs", "spec-loop")))

    def test_target_composes_as_container_root_plus_docs_spec_loop(self):
        key = "repo"
        target = dl.mount_target_for(key)
        self.assertEqual(target, dl.mount_point_for(key) + "/" + dl.DATA_REL)
        self.assertTrue(target.endswith("/docs/spec-loop"))

    def test_target_equals_root_arg_plus_join(self):
        # This is the load-bearing composition: server does
        # realpath(join(--root, "docs", "spec-loop")), which must equal target.
        key = "myrepo"
        container_root = dl.mount_point_for(key)  # the --root value
        server_join = container_root + "/" + dl.DATA_REL
        self.assertEqual(dl.mount_target_for(key), server_join)


# --------------------------------------------------------------------------
# Step 5 — build_run_argv SECURITY invariants
# --------------------------------------------------------------------------

class TestBuildRunArgvSecurity(unittest.TestCase):
    def setUp(self):
        self.port = dl.DEFAULT_PORT
        self.roots = ["/home/me/alpha", "/home/me/beta"]
        self.argv = dl.build_run_argv(dl.SINGLETON_NAME, dl.IMAGE_TAG,
                                      self.port, self.roots)

    def _flag_values(self, flag):
        return [self.argv[i + 1] for i, tok in enumerate(self.argv)
                if tok == flag and i + 1 < len(self.argv)]

    def test_loopback_publish_and_no_bare_publish(self):
        self.assertIn("-p", self.argv)
        publishes = self._flag_values("-p")
        self.assertIn(f"127.0.0.1:{self.port}:{self.port}", publishes)
        # No bare "{port}:{port}" publish that would expose 0.0.0.0.
        self.assertNotIn(f"{self.port}:{self.port}", publishes)

    def test_publish_host_port_equals_advertise_port(self):
        publish = self._flag_values("-p")[0]
        host_port = publish.split(":")[1]  # 127.0.0.1:<host>:<container>
        advertise = self._flag_values("--advertise-port")[0]
        self.assertEqual(host_port, advertise)

    def test_advertise_port_is_never_wildcard(self):
        self.assertEqual(self._flag_values("--advertise-port"),
                         [str(self.port)])
        self.assertNotIn("*", self._flag_values("--advertise-port"))

    def test_bind_host_only_ever_all_interfaces(self):
        binds = self._flag_values("--bind-host")
        self.assertEqual(binds, ["0.0.0.0"])

    def test_every_volume_is_readonly(self):
        vols = self._flag_values("-v")
        self.assertEqual(len(vols), len(self.roots))
        for v in vols:
            self.assertTrue(v.endswith(":ro"), v)

    def test_every_volume_target_composes_and_has_matching_root(self):
        vols = self._flag_values("-v")
        root_args = self._flag_values("--root")
        # one --root per mount
        self.assertEqual(len(root_args), len(vols))
        for v in vols:
            # v == <src>:<target>:ro ; target must end docs/spec-loop and
            # equal exactly one --root value + /docs/spec-loop.
            body = v[:-len(":ro")]
            _src, target = body.rsplit(":", 1)
            self.assertTrue(target.endswith("/" + dl.DATA_REL), target)
            container_root = target[:-(len(dl.DATA_REL) + 1)]
            self.assertIn(container_root, root_args)

    def test_cap_drop_all_present(self):
        self.assertIn("--cap-drop", self.argv)
        self.assertEqual(self._flag_values("--cap-drop"), ["ALL"])

    def test_no_dangerous_flags_or_socket_mount(self):
        self.assertNotIn("--privileged", self.argv)
        self.assertNotIn("0", self._flag_values("--user"))
        self.assertNotIn("root", self._flag_values("--user"))
        joined = " ".join(self.argv)
        self.assertNotIn("docker.sock", joined)
        self.assertNotIn("/var/run/docker.sock", joined)

    def test_detached_and_named_singleton(self):
        self.assertIn("-d", self.argv)
        self.assertEqual(self._flag_values("--name"), [dl.SINGLETON_NAME])

    def test_runs_the_existing_server(self):
        self.assertIn("scripts/dashboard_server.py", self.argv)
        self.assertIn(dl.IMAGE_TAG, self.argv)


# --------------------------------------------------------------------------
# Step 6 — scoped stop / rm targeting SINGLETON_NAME only
# --------------------------------------------------------------------------

class TestTeardownArgv(unittest.TestCase):
    def test_stop_targets_exactly_the_singleton_name(self):
        self.assertEqual(dl.build_stop_argv(dl.SINGLETON_NAME),
                         ["docker", "stop", dl.SINGLETON_NAME])

    def test_rm_targets_exactly_the_singleton_name_no_force(self):
        argv = dl.build_rm_argv(dl.SINGLETON_NAME)
        self.assertEqual(argv, ["docker", "rm", dl.SINGLETON_NAME])
        self.assertNotIn("-f", argv)
        self.assertNotIn("--force", argv)

    def test_teardown_sequence_is_scoped_stop_then_rm(self):
        seq = dl.build_teardown_argvs(dl.SINGLETON_NAME)
        self.assertEqual(seq, [["docker", "stop", dl.SINGLETON_NAME],
                               ["docker", "rm", dl.SINGLETON_NAME]])
        for argv in seq:
            self.assertIn(dl.SINGLETON_NAME, argv)
            self.assertNotIn("-f", argv)


# --------------------------------------------------------------------------
# Step 7 — ps/image argv + parsers + plan_launch
# --------------------------------------------------------------------------

class TestNameParsers(unittest.TestCase):
    def test_running_names_argv(self):
        self.assertEqual(dl.build_running_names_argv(),
                         ["docker", "ps", "--format", "{{.Names}}"])

    def test_all_names_argv_includes_stopped(self):
        argv = dl.build_all_names_argv()
        self.assertIn("-a", argv)
        self.assertEqual(argv[:2], ["docker", "ps"])

    def test_parse_running_names(self):
        names = dl.parse_running_names("foo\nspec-loop-dashboard\n\n  bar \n")
        self.assertEqual(names, {"foo", "spec-loop-dashboard", "bar"})

    def test_parse_all_names_empty(self):
        self.assertEqual(dl.parse_all_names(""), set())

    def test_image_present_argv(self):
        self.assertEqual(dl.build_image_present_argv(),
                         ["docker", "images", "-q", dl.IMAGE_TAG])

    def test_build_image_argv_pins_context(self):
        argv = dl.build_image_argv(dl.IMAGE_TAG, "/repo")
        self.assertEqual(argv, ["docker", "build", "-t", dl.IMAGE_TAG,
                                "-f", "/repo/Dockerfile", "/repo"])


class TestPlanLaunch(unittest.TestCase):
    def setUp(self):
        self.roots = ["/a", "/b"]

    def test_no_daemon_is_fallback(self):
        decision, argvs = dl.plan_launch(
            daemon_available=False, image_present=True,
            running_names=set(), all_names=set(),
            current_roots=None, desired=self.roots)
        self.assertEqual(decision, dl.FALLBACK)
        self.assertEqual(argvs, [])

    def test_image_absent_builds_then_runs(self):
        decision, argvs = dl.plan_launch(
            daemon_available=True, image_present=False,
            running_names=set(), all_names=set(),
            current_roots=None, desired=self.roots)
        self.assertEqual(decision, dl.BUILD_CREATE)
        self.assertEqual(argvs[0][:2], ["docker", "build"])
        self.assertEqual(argvs[-1][:2], ["docker", "run"])

    def test_no_singleton_creates(self):
        decision, argvs = dl.plan_launch(
            daemon_available=True, image_present=True,
            running_names=set(), all_names=set(),
            current_roots=None, desired=self.roots)
        self.assertEqual(decision, dl.CREATE)
        self.assertEqual(len(argvs), 1)
        self.assertEqual(argvs[0][:2], ["docker", "run"])

    def test_running_with_unchanged_roots_reuses(self):
        decision, argvs = dl.plan_launch(
            daemon_available=True, image_present=True,
            running_names={dl.SINGLETON_NAME}, all_names={dl.SINGLETON_NAME},
            current_roots=self.roots, desired=self.roots)
        self.assertEqual(decision, dl.REUSE)
        self.assertEqual(argvs, [])

    def test_running_with_changed_roots_recreates(self):
        decision, argvs = dl.plan_launch(
            daemon_available=True, image_present=True,
            running_names={dl.SINGLETON_NAME}, all_names={dl.SINGLETON_NAME},
            current_roots=["/a"], desired=self.roots)
        self.assertEqual(decision, dl.RECREATE)
        # scoped stop + rm, then run
        self.assertEqual(argvs[0], ["docker", "stop", dl.SINGLETON_NAME])
        self.assertEqual(argvs[1], ["docker", "rm", dl.SINGLETON_NAME])
        self.assertEqual(argvs[-1][:2], ["docker", "run"])

    def test_exists_but_stopped_recreates(self):
        # In all_names but not running -> scoped rm before run, never a bare run
        # that would collide on the name.
        decision, argvs = dl.plan_launch(
            daemon_available=True, image_present=True,
            running_names=set(), all_names={dl.SINGLETON_NAME},
            current_roots=None, desired=self.roots)
        self.assertEqual(decision, dl.RECREATE)
        self.assertEqual(argvs[0], ["docker", "stop", dl.SINGLETON_NAME])
        self.assertEqual(argvs[1], ["docker", "rm", dl.SINGLETON_NAME])
        self.assertEqual(argvs[-1][:2], ["docker", "run"])


# --------------------------------------------------------------------------
# Step 8 — main() dispatch via recording fake runner (no live docker)
# --------------------------------------------------------------------------

class TestRunIsShellFree(unittest.TestCase):
    def test_run_uses_list_args_and_no_shell(self):
        with mock.patch("dashboard_launcher.subprocess.run") as m:
            m.return_value = _proc(returncode=0)
            dl._run(["docker", "info"])
        args, kwargs = m.call_args
        self.assertEqual(args[0], ["docker", "info"])
        self.assertFalse(kwargs.get("shell", False))
        self.assertFalse(kwargs.get("check", True))


class TestMainStop(unittest.TestCase):
    def test_stop_emits_scoped_stop_then_rm_only(self):
        with mock.patch("dashboard_launcher.subprocess.run") as m:
            m.return_value = _proc(returncode=0)
            with contextlib.redirect_stdout(io.StringIO()):
                rc = dl.main(["--stop"])
        self.assertEqual(rc, 0)
        argvs = [c.args[0] for c in m.call_args_list]
        self.assertEqual(argvs, [["docker", "stop", dl.SINGLETON_NAME],
                                 ["docker", "rm", dl.SINGLETON_NAME]])
        for argv in argvs:
            self.assertNotIn("-f", argv)   # never an unscoped forced rm
            self.assertIn(dl.SINGLETON_NAME, argv)

    def test_stop_when_docker_absent_reports_and_does_not_crash(self):
        with mock.patch("dashboard_launcher.subprocess.run",
                        side_effect=FileNotFoundError("docker")):
            with contextlib.redirect_stderr(io.StringIO()):
                rc = dl.main(["--stop"])
        self.assertEqual(rc, 1)


class TestMainLaunch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self._tmp.name, "state")
        self._patch_state = mock.patch.object(dl, "STATE_DIR", self.state)
        self._patch_state.start()
        # Run from a real repo dir that has a docs/spec-loop so it survives prune.
        self.repo = os.path.join(self._tmp.name, "repo")
        os.makedirs(os.path.join(self.repo, dl.DATA_REL))
        self._cwd = os.getcwd()
        os.chdir(self.repo)

    def tearDown(self):
        os.chdir(self._cwd)
        self._patch_state.stop()
        self._tmp.cleanup()

    def test_docker_absent_falls_back_to_python_server(self):
        # docker info raises FileNotFoundError -> python fallback foreground.
        def run(argv, **kwargs):
            self.calls.append(argv)
            if argv[0] == "docker":
                raise FileNotFoundError("docker")
            return _proc(returncode=0)  # the python3 server "runs"
        self.calls = []
        with mock.patch("dashboard_launcher.subprocess.run", side_effect=run):
            with contextlib.redirect_stderr(io.StringIO()):
                rc = dl.main([])
        self.assertEqual(rc, 0)
        # The fallback server argv was invoked; no docker run happened.
        fallback = [c for c in self.calls if c[0] == "python3"]
        self.assertTrue(fallback)
        self.assertEqual(fallback[0],
                         ["python3", "scripts/dashboard_server.py",
                          "--root", "."])
        self.assertFalse([c for c in self.calls
                          if c[:2] == ["docker", "run"]])

    def test_name_conflict_reuses_no_fallback_no_unscoped_rm(self):
        # daemon up, image present, no singleton seen -> CREATE, but the run
        # loses a race and exits with a name-in-use error.
        conflict = _proc(returncode=125,
                         stderr='Conflict. The container name '
                                '"/spec-loop-dashboard" is already in use')

        def run(argv, **kwargs):
            self.calls.append(argv)
            two = tuple(argv[:2])
            if two == ("docker", "info"):
                return _proc(returncode=0)
            if two == ("docker", "images"):
                return _proc(returncode=0, stdout="sha256:present")
            if two == ("docker", "ps"):
                return _proc(returncode=0, stdout="")
            if two == ("docker", "run"):
                return conflict
            return _proc(returncode=0)
        self.calls = []
        with mock.patch("dashboard_launcher.subprocess.run", side_effect=run):
            with contextlib.redirect_stdout(io.StringIO()):
                rc = dl.main([])
        self.assertEqual(rc, 0)  # someone won the race; singleton is up
        # NEVER a python fallback on a name conflict.
        self.assertFalse([c for c in self.calls if c[0] == "python3"])
        # NEVER an unscoped/forced rm.
        for c in self.calls:
            self.assertNotIn("-f", c)

    def test_port_bound_gives_actionable_message(self):
        bound = _proc(returncode=125,
                      stderr="Bind for 127.0.0.1:8787 failed: "
                             "port is already allocated")

        def run(argv, **kwargs):
            self.calls.append(argv)
            two = tuple(argv[:2])
            if two == ("docker", "info"):
                return _proc(returncode=0)
            if two == ("docker", "images"):
                return _proc(returncode=0, stdout="sha256:present")
            if two == ("docker", "ps"):
                return _proc(returncode=0, stdout="")
            if two == ("docker", "run"):
                return bound
            return _proc(returncode=0)
        self.calls = []
        buf = []
        with mock.patch("dashboard_launcher.subprocess.run", side_effect=run):
            with mock.patch("sys.stderr") as err:
                err.write = lambda s: buf.append(s)
                rc = dl.main([])
        self.assertEqual(rc, 1)
        self.assertTrue(any("8787" in s and "busy" in s for s in buf),
                        "expected an actionable 'port busy' message")

    def test_successful_create_writes_registry_and_mountset(self):
        def run(argv, **kwargs):
            self.calls.append(argv)
            two = tuple(argv[:2])
            if two == ("docker", "info"):
                return _proc(returncode=0)
            if two == ("docker", "images"):
                return _proc(returncode=0, stdout="sha256:present")
            if two == ("docker", "ps"):
                return _proc(returncode=0, stdout="")
            if two == ("docker", "run"):
                return _proc(returncode=0, stdout="containerid")
            return _proc(returncode=0)
        self.calls = []
        with mock.patch("dashboard_launcher.subprocess.run", side_effect=run):
            with contextlib.redirect_stdout(io.StringIO()):
                rc = dl.main([])
        self.assertEqual(rc, 0)
        # Registry recorded this repo AFTER a successful run.
        reg = dl.read_registry(self.state)
        self.assertIn(os.path.realpath(self.repo), reg)
        # Mount set recorded so a later launch can detect a root-set change.
        self.assertEqual(dl.read_mount_set(self.state),
                         [os.path.realpath(self.repo)])
        # A docker run actually happened.
        self.assertTrue([c for c in self.calls if c[:2] == ["docker", "run"]])


if __name__ == "__main__":
    unittest.main()
