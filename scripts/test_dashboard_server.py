#!/usr/bin/env python3
"""Tests for the read-only spec-loop dashboard server (stdlib unittest).

Covers the pure data layer (scan_runs: wave derivation, honest labels, both
escalation marker forms, corrupt-dag tolerance) and the read-only HTTP layer's
risky security paths (path traversal, foreign Host header, non-GET method),
which are written first per the slice's test-first mandate.

`scripts/validate_marketplace.py` does NOT lint scripts/*.py, so this is the
sole automated guard on the server's behavior. Standard library only.

Usage:
    python3 scripts/test_dashboard_server.py
"""

import http.client
import json
import os
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dashboard_server as ds  # noqa: E402


# --------------------------------------------------------------------------
# Fixture builders
# --------------------------------------------------------------------------

def write_dag(run_dir: Path, slices: list, base_ref="alpha", base_sha="abc123"):
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "dag.json").write_text(
        json.dumps({"base_ref": base_ref, "base_sha": base_sha, "slices": slices})
    )


def slice_obj(sid, **overrides):
    """Build a slice dict; override any field via kwargs
    (deps, status, depth, parent, goal, ...)."""
    base = {
        "id": sid,
        "goal": "g",
        "files": [],
        "subsystems": [],
        "deps": [],
        "risk_tier": 2,
        "depth": 0,
        "parent": None,
        "status": "pending",
    }
    base.update(overrides)
    return base


def build_fixture(tmp: Path) -> Path:
    """Build a docs/spec-loop/ tree exercising every derivation branch."""
    docs = tmp / "docs" / "spec-loop"

    # --- normal run: mixed complete + dependent pending (waves) ---
    write_dag(docs / "run-normal", [
        slice_obj("s1", status="complete"),
        slice_obj("s2", deps=["s1"], status="pending"),       # runnable-pending
        slice_obj("s3", deps=["s2"], status="pending"),       # blocked-pending
    ])
    (docs / "run-normal" / "request.md").write_text(
        "# Request\n\nFirst meaningful line of the request.\nSecond line.\n"
    )
    (docs / "run-normal" / "decisions-log.md").write_text(
        "[intake] line one\n[s1] line two\n[s2] line three\n"
    )
    (docs / "run-normal" / "slice-s1-report.md").write_text("done")

    # --- split run: split parent + its <parent>.N children ---
    write_dag(docs / "run-split", [
        slice_obj("a", status="split"),                       # terminal, non-blocking
        slice_obj("a.1", deps=[], status="complete", depth=1, parent="a"),
        slice_obj("a.2", deps=["a.1"], status="pending", depth=1, parent="a"),
        # b depends on the SPLIT parent a -> a is terminal so b is NOT blocked
        slice_obj("b", deps=["a"], status="pending"),
    ])

    # --- escalation run: OPEN (escalation-gate) + ANSWERED forms ---
    write_dag(docs / "run-esc", [
        slice_obj("s1", status="complete"),
        slice_obj("s2", deps=["s1"], status="pending"),       # OPEN -> awaiting-human
        slice_obj("s3", deps=["s1"], status="pending"),       # ANSWERED -> redispatch
    ])
    (docs / "run-esc" / "escalations.md").write_text(
        "# Escalations\n\n"
        "## [s2] something ambiguous   (status: OPEN)\n"
        "Answer:\n\n"
        "## [s3] resolved thing   (status: ANSWERED)\n"
        "Answer: do it this way\n\n"
        "## [intake] Iron Council objects: premise unclear   (status: OPEN)\n"
        "Answer:\n"
    )

    # --- corrupt run: deliberately broken dag.json -> unreadable ---
    (docs / "run-corrupt").mkdir(parents=True)
    (docs / "run-corrupt" / "dag.json").write_text('{ "base_ref": "alpha", "slices": [ {bad')

    return docs


# --------------------------------------------------------------------------
# Pure data-layer tests
# --------------------------------------------------------------------------

class ScanRunsTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)
        self.docs = build_fixture(self.tmp)

    def tearDown(self):
        self.tmpdir.cleanup()

    def runs_by_id(self):
        return {r["run_id"]: r for r in ds.scan_runs(self.docs)}

    def test_corrupt_dag_is_unreadable_and_others_survive(self):
        runs = self.runs_by_id()
        self.assertEqual(runs["run-corrupt"]["status"], "unreadable")
        # The other four runs survived and parsed.
        for rid in ("run-normal", "run-split", "run-esc"):
            self.assertNotEqual(runs[rid].get("status"), "unreadable")
            self.assertIn("slices", runs[rid])

    def test_wave_derivation_normal(self):
        run = self.runs_by_id()["run-normal"]
        waves = run["waves"]
        # s1 complete; s2 (deps s1) runnable in wave 0; s3 (deps s2) wave 1.
        self.assertEqual(waves[0], ["s2"])
        self.assertEqual(waves[1], ["s3"])

    def test_honest_labels_normal(self):
        labels = {s["id"]: s["label"] for s in self.runs_by_id()["run-normal"]["slices"]}
        self.assertEqual(labels["s1"], "complete")
        self.assertEqual(labels["s2"], "runnable-pending")
        self.assertEqual(labels["s3"], "blocked-pending")

    def test_split_parent_terminal_does_not_block_dependents(self):
        run = self.runs_by_id()["run-split"]
        labels = {s["id"]: s["label"] for s in run["slices"]}
        self.assertEqual(labels["a"], "split")
        # b depends on split parent a, which is terminal -> b is runnable, not blocked.
        self.assertEqual(labels["b"], "runnable-pending")
        # a.2 depends on a.1 (complete) -> runnable; child convention preserved.
        self.assertEqual(labels["a.2"], "runnable-pending")
        child = next(s for s in run["slices"] if s["id"] == "a.2")
        self.assertEqual(child["depth"], 1)
        self.assertEqual(child["parent"], "a")
        # split parent must not appear in any wave (terminal).
        flat = [sid for w in run["waves"] for sid in w]
        self.assertNotIn("a", flat)
        self.assertIn("b", flat)

    def test_escalation_open_and_answered_labels(self):
        run = self.runs_by_id()["run-esc"]
        labels = {s["id"]: s["label"] for s in run["slices"]}
        self.assertEqual(labels["s2"], "awaiting-human")
        self.assertEqual(labels["s3"], "redispatch-pending")

    def test_filled_answer_overrides_open_header(self):
        # Per dashboard.md Step 6, a filled-in Answer: line means ANSWERED even
        # if the header still says OPEN (partial write) -> redispatch-pending.
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            docs = Path(d) / "docs" / "spec-loop"
            write_dag(docs / "r", [
                slice_obj("s1", status="complete"),
                slice_obj("s2", deps=["s1"], status="pending"),
            ])
            (docs / "r" / "escalations.md").write_text(
                "## [s2] thing   (status: OPEN)\n- Answer: human said go ahead\n"
            )
            run = next(x for x in ds.scan_runs(docs) if x["run_id"] == "r")
            labels = {s["id"]: s["label"] for s in run["slices"]}
            self.assertEqual(labels["s2"], "redispatch-pending")
            # ...and it is no longer reported as an OPEN escalation.
            self.assertNotIn("s2", {e["token"] for e in run["open_escalations"]})

    def test_intake_open_escalation_attaches_to_no_slice(self):
        run = self.runs_by_id()["run-esc"]
        tokens = {e["token"] for e in run["open_escalations"]}
        self.assertIn("intake", tokens)
        self.assertIn("s2", tokens)
        # intake escalation is not a slice id.
        slice_ids = {s["id"] for s in run["slices"]}
        self.assertNotIn("intake", slice_ids)

    def test_missing_optional_artifacts_are_absent_not_errors(self):
        # run-split has no request.md / decisions-log / reports.
        run = self.runs_by_id()["run-split"]
        self.assertEqual(run["request_excerpt"], "")
        self.assertEqual(run["decisions_tail"], [])
        for s in run["slices"]:
            self.assertFalse(s["has_report"])

    def test_report_presence_detected(self):
        run = self.runs_by_id()["run-normal"]
        reports = {s["id"]: s["has_report"] for s in run["slices"]}
        self.assertTrue(reports["s1"])
        self.assertFalse(reports["s2"])

    def test_request_excerpt_skips_heading(self):
        run = self.runs_by_id()["run-normal"]
        self.assertEqual(run["request_excerpt"], "First meaningful line of the request.")


# --------------------------------------------------------------------------
# Containment-helper unit tests
# --------------------------------------------------------------------------

class ContainmentTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name) / "root"
        self.root.mkdir()
        (self.root / "ok.txt").write_text("ok")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_inside_root_resolves(self):
        self.assertIsNotNone(ds.resolve_within(self.root, "ok.txt"))

    def test_traversal_rejected(self):
        self.assertIsNone(ds.resolve_within(self.root, "../etc/passwd"))

    def test_absolute_rejected(self):
        self.assertIsNone(ds.resolve_within(self.root, "/etc/passwd"))

    def test_null_byte_rejected(self):
        self.assertIsNone(ds.resolve_within(self.root, "ok.txt\x00"))

    def test_prefix_collision_sibling_rejected(self):
        sibling = self.root.parent / (self.root.name + "-evil")
        sibling.mkdir()
        (sibling / "secret").write_text("x")
        # A name that would pass a naive startswith but is outside root.
        self.assertIsNone(ds.resolve_within(self.root, "../" + self.root.name + "-evil/secret"))

    def test_escaping_symlink_rejected(self):
        outside = Path(self.tmpdir.name) / "outside"
        outside.mkdir()
        (outside / "leak").write_text("secret")
        link = self.root / "link"
        try:
            link.symlink_to(outside / "leak")
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unsupported on this platform")
        self.assertIsNone(ds.resolve_within(self.root, "link"))


# --------------------------------------------------------------------------
# HTTP-layer tests (risky paths first) — ephemeral port, real socket
# --------------------------------------------------------------------------

class HttpServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls.tmpdir.name)
        cls.docs = build_fixture(cls.tmp)
        assets = cls.tmp / "assets"
        assets.mkdir()
        (assets / "index.html").write_text("<!doctype html><title>dash</title>")
        (cls.tmp / "outside_secret.txt").write_text("TOP SECRET")
        cls.server = ds.build_server(cls.tmp, assets_dir=assets, port=0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmpdir.cleanup()

    def request(self, method, path, host=None, extra=None):
        host = host if host is not None else f"127.0.0.1:{self.port}"
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        # Use the low-level API so we control the Host header exactly:
        # skip_host suppresses the auto-added Host so we can omit or forge it.
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        if host != "__OMIT__":
            conn.putheader("Host", host)
        for k, v in (extra or {}).items():
            conn.putheader(k, v)
        conn.endheaders()
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body, resp.getheader("ETag")

    # --- risky security paths (written first) ---

    def test_run_id_traversal_returns_404(self):
        status, body, _ = self.request("GET", "/api/runs/..%2f..%2fetc%2fpasswd")
        self.assertEqual(status, 404)
        self.assertNotIn(b"root:", body)
        status2, _, _ = self.request("GET", "/api/runs/../../etc/passwd")
        self.assertEqual(status2, 404)

    def test_static_traversal_returns_404(self):
        for path in ("/../dashboard_server.py", "/../../outside_secret.txt",
                     "/..%2foutside_secret.txt"):
            status, body, _ = self.request("GET", path)
            self.assertEqual(status, 404, f"{path} -> {status}")
            self.assertNotIn(b"TOP SECRET", body)

    def test_foreign_host_rejected(self):
        status, _, _ = self.request("GET", "/api/runs", host="evil.com")
        self.assertEqual(status, 421)

    def test_substring_host_attack_rejected(self):
        status, _, _ = self.request(
            "GET", "/api/runs", host=f"localhost:{self.port}.evil.com")
        self.assertEqual(status, 421)

    def test_absent_host_rejected(self):
        status, _, _ = self.request("GET", "/api/runs", host="__OMIT__")
        self.assertEqual(status, 421)

    def test_non_get_method_returns_405(self):
        for method in ("POST", "PUT", "DELETE"):
            status, _, _ = self.request(method, "/api/runs")
            self.assertEqual(status, 405, f"{method} -> {status}")

    def test_404_body_has_no_path_oracle(self):
        # "no such run" and "escapes root" must look identical.
        missing, body_missing, _ = self.request("GET", "/api/runs/does-not-exist")
        escape, body_escape, _ = self.request("GET", "/api/runs/../../etc/passwd")
        self.assertEqual(missing, 404)
        self.assertEqual(escape, 404)
        self.assertEqual(body_missing, body_escape)

    # --- endpoint behavior ---

    def test_api_runs_lists_all_runs(self):
        status, body, _ = self.request("GET", "/api/runs")
        self.assertEqual(status, 200)
        data = json.loads(body)
        ids = {r["run_id"] for r in data["runs"]}
        self.assertEqual(ids, {"run-normal", "run-split", "run-esc", "run-corrupt"})

    def test_api_run_detail(self):
        status, body, _ = self.request("GET", "/api/runs/run-normal")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["run_id"], "run-normal")
        self.assertIn("waves", data)
        self.assertIn("decisions_tail", data)

    def test_unreadable_run_detail_is_200_envelope(self):
        status, body, _ = self.request("GET", "/api/runs/run-corrupt")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["status"], "unreadable")

    def test_etag_304_on_unchanged(self):
        status, _, etag = self.request("GET", "/api/runs/run-normal")
        self.assertEqual(status, 200)
        self.assertIsNotNone(etag)
        status2, _, _ = self.request(
            "GET", "/api/runs/run-normal", extra={"If-None-Match": etag})
        self.assertEqual(status2, 304)

    def test_collection_etag_busts_when_run_added(self):
        _, _, etag = self.request("GET", "/api/runs")
        self.assertIsNotNone(etag)
        write_dag(self.docs / "run-new", [slice_obj("s1", status="pending")])
        try:
            status, _, _ = self.request(
                "GET", "/api/runs", extra={"If-None-Match": etag})
            self.assertEqual(status, 200)  # cache busted, not 304
        finally:
            import shutil
            shutil.rmtree(self.docs / "run-new")

    def test_index_served_at_root(self):
        status, body, _ = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"<!doctype html>", body.lower())

    def test_head_allowed(self):
        status, body, _ = self.request("HEAD", "/api/runs")
        self.assertEqual(status, 200)
        self.assertEqual(body, b"")


# --------------------------------------------------------------------------
# Part A — bind host / advertised-port decoupling (security: anti-rebinding)
# --------------------------------------------------------------------------

class BindHostAllowlistTests(unittest.TestCase):
    """The Host-header allowlist must derive from the ADVERTISED port and stay
    hardcoded to loopback host strings — binding 0.0.0.0 must NEVER widen it."""

    def test_allowlist_derives_from_advertised_port_only(self):
        # advertised port differs from bound port -> allowlist keys off advertised.
        allowed = ds._host_allowlist(9999)
        self.assertEqual(allowed, {"127.0.0.1:9999", "localhost:9999"})

    def test_allowlist_never_contains_bind_host_zero(self):
        # No entry may ever reference 0.0.0.0, regardless of bind host.
        for port in (0, 8787, 9999):
            allowed = ds._host_allowlist(port)
            self.assertFalse(any("0.0.0.0" in h for h in allowed),
                             f"allowlist leaked 0.0.0.0: {allowed}")

    def test_build_server_binds_configured_host(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            server = ds.build_server(Path(d), port=0,
                                     net=ds.NetworkConfig(bind_host="0.0.0.0"))
            try:
                # Bound host reflects the request; allowlist stays loopback-only.
                self.assertEqual(server.server_address[0], "0.0.0.0")
                handler = server.RequestHandlerClass
                self.assertFalse(any("0.0.0.0" in h for h in handler.allowed_hosts))
            finally:
                server.server_close()

    def test_foreign_and_star_host_421_when_bound_zero(self):
        # The load-bearing anti-DNS-rebinding assertion: binding 0.0.0.0 does not
        # relax the Host allowlist. We connect over loopback (reachable) but forge
        # the Host header.
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            docs = Path(d) / "docs" / "spec-loop"
            write_dag(docs / "r", [slice_obj("s1", status="pending")])
            assets = Path(d) / "assets"
            assets.mkdir()
            (assets / "index.html").write_text("<!doctype html>")
            server = ds.build_server(Path(d), assets_dir=assets, port=0,
                                     net=ds.NetworkConfig(bind_host="0.0.0.0"))
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for bad_host in ("evil.com", "*", f"0.0.0.0:{port}",
                                 f"container-host:{port}"):
                    status = self._request_host(port, bad_host)
                    self.assertEqual(status, 421, f"{bad_host!r} -> {status}")
                # ...but the advertised loopback Host still works.
                self.assertEqual(self._request_host(port, f"127.0.0.1:{port}"), 200)
            finally:
                server.shutdown()
                server.server_close()

    def test_advertise_port_overrides_bound_port_in_allowlist(self):
        # When advertise_port is set, the allowlist uses it, not the bound port,
        # so a Host on the ADVERTISED port is accepted even though the socket is
        # bound to a different (ephemeral) port. We reach the socket over its real
        # bound port but forge the advertised Host.
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            docs = Path(d) / "docs" / "spec-loop"
            write_dag(docs / "r", [slice_obj("s1", status="pending")])
            server = ds.build_server(
                Path(d), port=0,
                net=ds.NetworkConfig(bind_host="0.0.0.0", advertise_port=8080))
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                # Host on the ADVERTISED port -> accepted.
                self.assertEqual(self._request_host(port, "127.0.0.1:8080"), 200)
                # Host on the (real) bound port -> NOT in allowlist -> 421.
                self.assertEqual(self._request_host(port, f"127.0.0.1:{port}"), 421)
            finally:
                server.shutdown()
                server.server_close()

    def test_advertise_port_zero_falls_back_to_bound_port(self):
        # An explicit advertise_port=0 is falsy and must degrade to the real bound
        # port (a reachable loopback allowlist), never an unreachable ":0" entry.
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            docs = Path(d) / "docs" / "spec-loop"
            write_dag(docs / "r", [slice_obj("s1", status="pending")])
            server = ds.build_server(Path(d), port=0,
                                     net=ds.NetworkConfig(advertise_port=0))
            port = server.server_address[1]
            handler = server.RequestHandlerClass
            self.assertNotIn("127.0.0.1:0", handler.allowed_hosts)
            self.assertIn(f"127.0.0.1:{port}", handler.allowed_hosts)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                self.assertEqual(self._request_host(port, f"127.0.0.1:{port}"), 200)
            finally:
                server.shutdown()
                server.server_close()

    @staticmethod
    def _request_host(port, host):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.putrequest("GET", "/api/runs", skip_host=True,
                        skip_accept_encoding=True)
        conn.putheader("Host", host)
        conn.endheaders()
        resp = conn.getresponse()
        resp.read()
        conn.close()
        return resp.status


# --------------------------------------------------------------------------
# Part B — multi-root aggregation, namespacing, per-root containment
# --------------------------------------------------------------------------

class MultiRootTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self.tmpdir.name)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _root(self, name):
        """Create a repo root <tmp>/<name> with a docs/spec-loop dir."""
        root = self.tmp / name
        (root / "docs" / "spec-loop").mkdir(parents=True)
        return root

    def test_single_root_is_transparent_no_namespacing(self):
        # scan_all_roots with exactly one root -> bare run_id, no 'root' field.
        root = self._root("repo")
        write_dag(root / "docs" / "spec-loop" / "run-x",
                  [slice_obj("s1", status="pending")])
        runs = ds.scan_all_roots([str(root)])
        self.assertEqual([r["run_id"] for r in runs], ["run-x"])
        self.assertNotIn("root", runs[0])

    def test_multi_root_namespaces_run_ids_no_collision(self):
        # Two roots each with an identically-named run -> two distinct ids.
        a = self._root("repo-a")
        b = self._root("repo-b")
        write_dag(a / "docs" / "spec-loop" / "run-x",
                  [slice_obj("s1", status="pending")])
        write_dag(b / "docs" / "spec-loop" / "run-x",
                  [slice_obj("s1", status="pending")])
        runs = ds.scan_all_roots([str(a), str(b)])
        ids = sorted(r["run_id"] for r in runs)
        self.assertEqual(ids, ["repo-a:run-x", "repo-b:run-x"])
        # Every run carries its owning root key.
        self.assertTrue(all("root" in r for r in runs))

    def test_multi_root_ordering_is_deterministic_and_stable(self):
        # Colliding basenames get a deterministic, stable de-dup — same input
        # order -> same namespaced ids across repeated calls.
        outer1 = self.tmp / "x" / "repo"
        outer2 = self.tmp / "y" / "repo"
        for r in (outer1, outer2):
            (r / "docs" / "spec-loop").mkdir(parents=True)
            write_dag(r / "docs" / "spec-loop" / "run-x",
                      [slice_obj("s1", status="pending")])
        first = sorted(r["run_id"] for r in
                       ds.scan_all_roots([str(outer1), str(outer2)]))
        second = sorted(r["run_id"] for r in
                        ds.scan_all_roots([str(outer1), str(outer2)]))
        self.assertEqual(first, second)
        # Colliding basenames must still yield two distinct ids.
        self.assertEqual(len(set(first)), 2)

    def test_colliding_basenames_get_concrete_disjoint_suffixes(self):
        # Guard the de-dup SCHEME, not just its count: the two colliding "repo"
        # roots must map to concrete, disjoint namespaced ids in input order.
        outer1 = self.tmp / "x" / "repo"
        outer2 = self.tmp / "y" / "repo"
        for r in (outer1, outer2):
            (r / "docs" / "spec-loop").mkdir(parents=True)
            write_dag(r / "docs" / "spec-loop" / "run-x",
                      [slice_obj("s1", status="pending")])
        ids = sorted(r["run_id"] for r in
                     ds.scan_all_roots([str(outer1), str(outer2)]))
        self.assertEqual(ids, ["repo#1:run-x", "repo#2:run-x"])

    def test_single_root_run_id_with_colon_resolves_transparently(self):
        # A single-root run whose basename literally contains ':' must NOT be
        # split/namespaced — the empty-key branch resolves it as-is.
        root = self._root("repo")
        write_dag(root / "docs" / "spec-loop" / "a:b",
                  [slice_obj("s1", status="pending")])
        runs = ds.scan_all_roots([str(root)])
        self.assertEqual([r["run_id"] for r in runs], ["a:b"])
        self.assertNotIn("root", runs[0])


class MultiRootHttpTests(unittest.TestCase):
    """Per-root containment over a real socket — a namespaced id may never reach
    a sibling root, and crafted ids return a uniform no-oracle 404."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls.tmpdir.name)
        cls.root_a = cls.tmp / "repo-a"
        cls.root_b = cls.tmp / "repo-b"
        for root, only_run in ((cls.root_a, "only-a"), (cls.root_b, "only-b")):
            (root / "docs" / "spec-loop").mkdir(parents=True)
            write_dag(root / "docs" / "spec-loop" / only_run,
                      [slice_obj("s1", status="complete")])
        # A secret file under root A, outside its docs/spec-loop, to prove no escape.
        (cls.root_a / "SECRET.txt").write_text("TOP SECRET A")
        assets = cls.tmp / "assets"
        assets.mkdir()
        (assets / "index.html").write_text("<!doctype html>")
        cls.server = ds.build_server([str(cls.root_a), str(cls.root_b)],
                                     assets_dir=assets, port=0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmpdir.cleanup()

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest("GET", path, skip_accept_encoding=True)
        conn.putheader("Host", f"127.0.0.1:{self.port}")
        conn.endheaders()
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def test_api_runs_aggregates_both_roots_namespaced(self):
        status, body = self._get("/api/runs")
        self.assertEqual(status, 200)
        ids = {r["run_id"] for r in json.loads(body)["runs"]}
        self.assertEqual(ids, {"repo-a:only-a", "repo-b:only-b"})

    def test_namespaced_detail_resolves_to_owning_root(self):
        status, body = self._get("/api/runs/repo-a%3Aonly-a")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["run_id"], "repo-a:only-a")

    def test_run_from_one_root_not_reachable_under_another(self):
        # 'only-b' exists only in root B; asking for it namespaced to root A misses.
        status, _ = self._get("/api/runs/repo-a%3Aonly-b")
        self.assertEqual(status, 404)

    def test_bogus_root_key_and_bare_id_miss_uniformly(self):
        # A syntactically valid but unknown key, and a bare (unqualified) id, must
        # both return the SAME no-oracle 404 body as a matched-key missing run —
        # never a fall-back that searches all roots.
        _, plain_miss = self._get("/api/runs/repo-a%3Adoes-not-exist")
        for path in ("/api/runs/nosuchrepo%3Aonly-a",  # unknown key
                     "/api/runs/only-a",               # bare id, no key
                     "/api/runs/%3Aonly-a"):           # empty key
            status, body = self._get(path)
            self.assertEqual(status, 404, f"{path} -> {status}")
            self.assertEqual(body, plain_miss, f"path oracle on {path}")

    def test_crafted_namespaced_id_cannot_escape_or_oracle(self):
        # Uniform no-path-oracle 404: a crafted traversal id and a plain miss must
        # be byte-identical, and neither leaks the sibling root or a secret.
        _, plain_miss = self._get("/api/runs/repo-a%3Adoes-not-exist")
        crafted = (
            "/api/runs/repo-a%3A..%2f..%2frepo-b%2fdocs%2fspec-loop%2fonly-b",
            "/api/runs/repo-a%3A..%2f..%2fSECRET.txt",
            "/api/runs/..%2f..%2frepo-b%2fdocs%2fspec-loop%2fonly-b",
        )
        for path in crafted:
            status, body = self._get(path)
            self.assertEqual(status, 404, f"{path} -> {status}")
            self.assertEqual(body, plain_miss, f"path oracle on {path}")
            self.assertNotIn(b"SECRET", body)

    def test_multi_root_foreign_host_still_421(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest("GET", "/api/runs", skip_host=True,
                        skip_accept_encoding=True)
        conn.putheader("Host", "evil.com")
        conn.endheaders()
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 421)


if __name__ == "__main__":
    unittest.main()
