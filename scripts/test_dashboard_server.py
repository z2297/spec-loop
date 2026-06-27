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


if __name__ == "__main__":
    unittest.main()
