#!/usr/bin/env python3
"""Read-only HTTP server + data layer for the spec-loop dashboard.

Serves a strictly READ-ONLY view of spec-loop runs from their durable
artifacts under ``docs/spec-loop/<run-id>/``. It reuses the exact derivation
rules of the terminal command ``plugins/spec-loop/commands/dashboard.md`` —
there is a single source of truth for run state (``dag.json``) and a single
source of derivation logic (the ``scan_runs`` layer below). Standard library
only: zero third-party dependencies, no node/npm/build tooling.

Two clean layers:

  (A) ``scan_runs(docs_root)`` — a PURE, importable function that discovers
      runs, parses each ``dag.json``, derives waves + honest per-slice labels,
      reads OPEN escalations (both marker forms incl. the intake-scoped form),
      and tolerates a half-written ``dag.json`` by emitting that run as
      ``unreadable`` without dropping siblings or inventing state.

  (B) A read-only ``http.server`` layer with hard security guardrails:
      GET/HEAD only (405 otherwise); binds 127.0.0.1 only; a Host-header
      allowlist (anti-DNS-rebinding); path-traversal-safe run resolution that
      enumerates discovered run dirs and matches by exact basename; every file
      read canonicalized via ``os.path.realpath`` and asserted to stay under a
      bounded root; bounded counts and bytes; ETag/304. It mutates nothing,
      shells out to nothing, and writes no files.

Usage:
    python3 scripts/dashboard_server.py [--port 8787] [--root .]

    # then open the printed http://127.0.0.1:<port>/ URL.
"""

import argparse
import glob
import hashlib
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# --- bounds (real guardrails, not aspirational) ---
MAX_RUNS = 500              # cap runs scanned per request
MAX_FILE_BYTES = 1_000_000  # cap any single artifact read into memory
DECISIONS_TAIL_LINES = 12   # cap decisions-log tail length
REQUEST_EXCERPT_CHARS = 240 # cap the one-line request excerpt

DEFAULT_PORT = 8787
DATA_SUBPATH = ("docs", "spec-loop")
ASSETS_SUBPATH = "dashboard_assets"  # relative to this script's dir


# ==========================================================================
# Shared path-containment helper (used for BOTH data reads and asset reads)
# ==========================================================================

def resolve_within(root, relpath):
    """Resolve ``relpath`` under ``root``, returning a safe absolute path or
    ``None`` if it escapes the root.

    Rejects null bytes, absolute paths, and ``..`` traversal, then canonicalizes
    via ``os.path.realpath`` (following symlinks) and asserts the result stays
    under ``realpath(root)`` using ``os.path.commonpath`` — so a sibling like
    ``<root>-evil`` cannot pass a naive prefix check, and a symlink escaping the
    root is rejected. ``root`` is realpath'd too (macOS ``/tmp`` -> ``/private/tmp``).
    """
    relpath = str(relpath)
    if "\x00" in relpath or os.path.isabs(relpath):
        return None
    real_root = os.path.realpath(str(root))
    candidate = os.path.realpath(os.path.join(real_root, relpath))
    try:
        if os.path.commonpath([real_root, candidate]) != real_root:
            return None
    except ValueError:
        # Different drives / mixed absolute-relative -> not contained.
        return None
    return candidate


def _read_text_capped(path):
    """Read up to MAX_FILE_BYTES of text, or return '' if absent/unreadable."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(MAX_FILE_BYTES)
    except (OSError, ValueError):
        return ""


# ==========================================================================
# Layer (A): pure data layer — derivation rules per dashboard.md Steps 1-8
# ==========================================================================

def scan_runs(docs_root):
    """Discover and parse every run under ``docs_root`` (a ``docs/spec-loop``
    directory). Returns a list of run dicts. A run with a half-written
    ``dag.json`` is emitted as ``{"run_id", "status": "unreadable"}`` rather
    than dropped. Pure: reads files, never writes."""
    docs_root = Path(docs_root)
    runs = []
    pattern = str(docs_root / "*" / "dag.json")
    for dag_path in sorted(glob.glob(pattern))[:MAX_RUNS]:
        run_dir = Path(dag_path).parent
        runs.append(_scan_one_run(run_dir))
    return runs


def _scan_one_run(run_dir):
    run_id = run_dir.name
    try:
        dag = json.loads((run_dir / "dag.json").read_text())
        slices = dag["slices"]
        if not isinstance(slices, list):
            raise ValueError("slices is not a list")
    except (OSError, ValueError, KeyError, TypeError):
        # Mirrors the command's "state momentarily unreadable" degrade.
        return {"run_id": run_id, "status": "unreadable"}

    open_escs = _parse_open_escalations(run_dir)
    answered_ids = _parse_answered_slice_ids(run_dir)
    open_slice_ids = {e["token"] for e in open_escs if e["token"] != "intake"}
    statuses = {s.get("id"): s.get("status") for s in slices}

    enriched = [
        _label_slice(s, statuses, open_slice_ids, answered_ids, run_dir)
        for s in slices
    ]
    return {
        "run_id": run_id,
        "base_ref": dag.get("base_ref"),
        "base_sha": dag.get("base_sha"),
        "slices": enriched,
        "waves": _derive_waves(slices),
        "open_escalations": open_escs,
        "request_excerpt": _request_excerpt(run_dir),
        "decisions_tail": _decisions_tail(run_dir),
        "counts": _count_labels(enriched),
    }


def _dep_satisfied(dep_id, statuses):
    """A dep is satisfied when complete OR split (split is terminal/non-blocking)."""
    return statuses.get(dep_id) in ("complete", "split")


def _label_slice(s, statuses, open_slice_ids, answered_ids, run_dir):
    sid = s.get("id")
    status = s.get("status")
    if status == "complete":
        label = "complete"
    elif status == "split":
        label = "split"
    elif sid in open_slice_ids:
        label = "awaiting-human"
    elif sid in answered_ids:
        label = "redispatch-pending"
    elif all(_dep_satisfied(d, statuses) for d in s.get("deps", [])):
        label = "runnable-pending"
    else:
        label = "blocked-pending"
    report = run_dir / f"slice-{sid}-report.md"
    return {**s, "label": label, "has_report": report.is_file()}


def _derive_waves(slices):
    """Derive waves: a wave = every pending slice whose deps are all satisfied
    (complete or split). Iterate, assigning each later pending slice to the
    first wave at which its deps are met. ``split`` slices are terminal and
    never appear in a wave."""
    statuses = {s.get("id"): s.get("status") for s in slices}
    pending = [s for s in slices if s.get("status") == "pending"]
    done = {sid for sid, st in statuses.items() if st in ("complete", "split")}
    waves = []
    remaining = list(pending)
    while remaining:
        ready = [s for s in remaining
                 if all(d in done for d in s.get("deps", []))]
        if not ready:
            break  # unsatisfiable deps (cycle / missing) — stop, don't loop
        waves.append([s["id"] for s in ready])
        done.update(s["id"] for s in ready)
        ready_ids = {s["id"] for s in ready}
        remaining = [s for s in remaining if s["id"] not in ready_ids]
    return waves


def _count_labels(enriched):
    counts = {}
    for s in enriched:
        counts[s["label"]] = counts.get(s["label"], 0) + 1
    return counts


def _parse_open_escalations(run_dir):
    """Parse OPEN escalation headers (both marker forms) from escalations.md.

    Forms (per dashboard.md Step 6):
      - escalation-gate: ``## [<slice-id>] <title>   (status: OPEN)``
      - iron-council:    ``## [<id-or-intake>] Iron Council objects: … (status: OPEN)``
    Returns ``[{"token", "title"}]``; the bracket token may be a slice id or
    the literal ``intake`` (which joins no slice row)."""
    return [
        {"token": tok, "title": title}
        for tok, title, state in _iter_escalation_headers(run_dir)
        if state == "OPEN"
    ]


def _parse_answered_slice_ids(run_dir):
    return {
        tok for tok, _title, state in _iter_escalation_headers(run_dir)
        if state == "ANSWERED"
    }


def _iter_escalation_headers(run_dir):
    """Yield ``(token, title, state)`` for each escalation header, where state
    is 'OPEN', 'ANSWERED', or '' (unknown)."""
    text = _read_text_capped(run_dir / "escalations.md")
    for line in text.splitlines():
        if not line.startswith("## ["):
            continue
        close = line.find("]", 4)
        if close == -1:
            continue
        token = line[4:close].strip()
        rest = line[close + 1:]
        state = ""
        if "(status: OPEN)" in rest:
            state = "OPEN"
        elif "(status: ANSWERED)" in rest:
            state = "ANSWERED"
        yield token, rest.split("(status:")[0].strip(), state


def _request_excerpt(run_dir):
    """One-line excerpt of request.md: the first non-blank, non-heading line."""
    text = _read_text_capped(run_dir / "request.md")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped[:REQUEST_EXCERPT_CHARS]
    return ""


def _decisions_tail(run_dir):
    """Last few non-blank lines of decisions-log.md (bounded)."""
    text = _read_text_capped(run_dir / "decisions-log.md")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-DECISIONS_TAIL_LINES:]


def _run_etag(run_dir):
    """Per-run ETag from the mtimes of dag.json + sibling artifacts."""
    parts = []
    for name in ("dag.json", "request.md", "escalations.md", "decisions-log.md"):
        try:
            parts.append(f"{name}:{os.path.getmtime(run_dir / name):.6f}")
        except OSError:
            parts.append(f"{name}:-")
    return _etag(";".join(parts))


def _etag(material):
    return '"' + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32] + '"'


# ==========================================================================
# Layer (B): read-only HTTP handler
# ==========================================================================

class DashboardHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    # Injected by build_server:
    data_root = ""     # realpath of <root>/docs/spec-loop
    assets_root = ""   # realpath of the bundled assets dir
    allowed_hosts = set()

    server_version = "spec-loop-dashboard"

    # --- only GET and HEAD exist; everything else is 405 ---

    def do_GET(self):
        self._handle(write_body=True)

    def do_HEAD(self):
        self._handle(write_body=False)

    def _handle(self, write_body):
        if not self._host_allowed():
            self._send(421, b"misdirected request", "text/plain", write_body)
            return
        route = self.path.split("?", 1)[0]
        if route == "/api/runs":
            self._serve_api_runs(write_body)
        elif route.startswith("/api/runs/"):
            self._serve_api_run_detail(route[len("/api/runs/"):], write_body)
        else:
            self._serve_static(route, write_body)

    # Any other verb is rejected uniformly.
    def _reject_method(self):
        self._send(405, b"method not allowed", "text/plain", True)

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _reject_method

    # --- security gates ---

    def _host_allowed(self):
        host = self.headers.get("Host")
        return host is not None and host in self.allowed_hosts

    # --- endpoints ---

    def _serve_api_runs(self, write_body):
        runs = scan_runs(self.data_root)
        etag = _etag("|".join(self._collection_material(runs)))
        if self._if_none_match(etag):
            self._send(304, b"", "application/json", False, etag=etag)
            return
        payload = {"runs": runs}
        self._send_json(payload, write_body, etag=etag)

    def _collection_material(self, runs):
        out = []
        for r in runs:
            rd = Path(self.data_root) / r["run_id"]
            out.append(f"{r['run_id']}:{_run_etag(rd)}")
        return out

    def _serve_api_run_detail(self, raw_id, write_body):
        # Path-traversal-safe: enumerate discovered run dirs, exact-match basename.
        run_id = raw_id.rstrip("/")
        known = {Path(p).parent.name for p in
                 glob.glob(str(Path(self.data_root) / "*" / "dag.json"))}
        if run_id not in known:
            # Same 404 for "no such run" and "escapes root" — no path oracle.
            self._send(404, b"not found", "text/plain", write_body)
            return
        run_dir = resolve_within(self.data_root, run_id)
        if run_dir is None or not os.path.isdir(run_dir):
            self._send(404, b"not found", "text/plain", write_body)
            return
        etag = _run_etag(Path(run_dir))
        if self._if_none_match(etag):
            self._send(304, b"", "application/json", False, etag=etag)
            return
        self._send_json(_scan_one_run(Path(run_dir)), write_body, etag=etag)

    def _serve_static(self, route, write_body):
        rel = route.lstrip("/") or "index.html"
        target = resolve_within(self.assets_root, rel)
        if target is None or not os.path.isfile(target):
            self._send(404, b"not found", "text/plain", write_body)
            return
        body = self._read_asset(target)
        if body is None:
            self._send(404, b"not found", "text/plain", write_body)
            return
        self._send(200, body, _content_type(target), write_body)

    def _read_asset(self, target):
        try:
            with open(target, "rb") as fh:
                return fh.read(MAX_FILE_BYTES)
        except OSError:
            return None

    # --- response helpers ---

    def _if_none_match(self, etag):
        return self.headers.get("If-None-Match") == etag

    def _send_json(self, obj, write_body, etag=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(200, body, "application/json; charset=utf-8", write_body, etag=etag)

    def _send(self, status, body, content_type, write_body, etag=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if etag:
            self.send_header("ETag", etag)
        self.end_headers()
        if write_body and body:
            self.wfile.write(body)

    def log_message(self, *args):
        pass  # quiet by default


_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}


def _content_type(path):
    return _CONTENT_TYPES.get(Path(path).suffix.lower(), "application/octet-stream")


# ==========================================================================
# Wiring
# ==========================================================================

def build_server(root, assets_dir=None, port=DEFAULT_PORT):
    """Build (but do not start) a ThreadingHTTPServer bound to 127.0.0.1.

    ``root`` is the repo root; the data root is fixed to
    ``realpath(root/docs/spec-loop)`` and resolved once here as the single
    trust boundary. ``assets_dir`` defaults to this script's bundled
    ``dashboard_assets/``. Port 0 -> an ephemeral port (used by tests)."""
    data_root = os.path.realpath(os.path.join(str(root), *DATA_SUBPATH))
    if assets_dir is None:
        assets_dir = Path(__file__).resolve().parent / ASSETS_SUBPATH
    assets_root = os.path.realpath(str(assets_dir))

    handler = type("BoundDashboardHandler", (DashboardHandler,), {
        "data_root": data_root,
        "assets_root": assets_root,
        "allowed_hosts": _host_allowlist(port),
    })
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    # If port 0 was requested, fix the allowlist to the real assigned port.
    if port == 0:
        handler.allowed_hosts = _host_allowlist(server.server_address[1])
    return server


def _host_allowlist(port):
    return {f"127.0.0.1:{port}", f"localhost:{port}"}


def main():
    ap = argparse.ArgumentParser(description="read-only spec-loop dashboard server")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"port to bind on 127.0.0.1 (default: {DEFAULT_PORT})")
    ap.add_argument("--root", default=".",
                    help="repo root containing docs/spec-loop (default: cwd)")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    data_root = os.path.realpath(os.path.join(str(root), *DATA_SUBPATH))
    if not os.path.isdir(data_root):
        print(f"warning: {data_root} does not exist — no runs will be served",
              file=sys.stderr)

    server = build_server(root, port=args.port)
    bound_port = server.server_address[1]
    print(f"spec-loop dashboard (read-only) serving {data_root}")
    print(f"  open http://127.0.0.1:{bound_port}/   (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
