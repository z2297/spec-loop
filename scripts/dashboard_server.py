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
from collections import namedtuple
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# A response value object: groups the four output fields so handler helpers
# pass one argument instead of four (etag defaults to None).
Response = namedtuple("Response", "status body content_type etag")
Response.__new__.__defaults__ = (None,)


def _text(status, message):
    return Response(status, message, "text/plain")

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

    Rejects null bytes and absolute paths, then canonicalizes via
    ``os.path.realpath`` (collapsing ``..`` and following symlinks) and asserts
    the result stays under ``realpath(root)`` using ``os.path.commonpath`` — so
    ``..`` traversal cannot escape, and a sibling like
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
    ctx = {
        "statuses": {s.get("id"): s.get("status") for s in slices},
        "open_slice_ids": {e["token"] for e in open_escs if e["token"] != "intake"},
        "answered_ids": _parse_answered_slice_ids(run_dir),
    }
    enriched = [_label_slice(s, ctx, run_dir) for s in slices]
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


def _label_slice(s, ctx, run_dir):
    """Attach the honest derived label + report presence to a slice dict.

    ``ctx`` bundles {statuses, open_slice_ids, answered_ids} (see _scan_one_run)."""
    sid = s.get("id")
    report = run_dir / f"slice-{sid}-report.md"
    return {**s, "label": _derive_label(s, ctx), "has_report": report.is_file()}


def _derive_label(s, ctx):
    """The six honest labels per dashboard.md Step 4, in precedence order."""
    sid, status = s.get("id"), s.get("status")
    if status in ("complete", "split"):
        return status
    if sid in ctx["open_slice_ids"]:
        return "awaiting-human"
    if sid in ctx["answered_ids"]:
        return "redispatch-pending"
    deps_met = all(_dep_satisfied(d, ctx["statuses"]) for d in s.get("deps", []))
    return "runnable-pending" if deps_met else "blocked-pending"


def _derive_waves(slices):
    """Derive waves: a wave = every pending slice whose deps are all satisfied
    (complete or split). Iterate, assigning each later pending slice to the
    first wave at which its deps are met. ``split`` slices are terminal and
    never appear in a wave."""
    done = _completed_ids(slices)
    remaining = _pending_slices(slices)
    waves = []
    while remaining:
        ready_ids = _ready_ids(remaining, done)
        if not ready_ids:
            break  # unsatisfiable deps (cycle / missing) — stop, don't loop
        waves.append(ready_ids)
        done |= set(ready_ids)
        remaining = _without(remaining, ready_ids)
    return waves


def _completed_ids(slices):
    """Ids whose status is terminal-satisfied (complete or split)."""
    return {s.get("id") for s in slices
            if s.get("status") in ("complete", "split")}


def _pending_slices(slices):
    return [s for s in slices if s.get("status") == "pending"]


def _ready_ids(remaining, done):
    """Ids of pending slices whose every dep is already satisfied."""
    return [s["id"] for s in remaining
            if all(d in done for d in s.get("deps", []))]


def _without(slices, exclude_ids):
    excluded = set(exclude_ids)
    return [s for s in slices if s["id"] not in excluded]


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
    """Yield ``(token, title, state)`` for each escalation block, where state
    is 'OPEN', 'ANSWERED', or '' (unknown).

    Per dashboard.md Step 6, an entry is ANSWERED when EITHER its header carries
    ``(status: ANSWERED)`` OR its ``Answer:`` line is filled in — two independent
    signals — so a partial write (Answer filled, header still OPEN) is treated as
    ANSWERED/redispatch-pending, not awaiting-human. So this scans each block's
    body lines for a non-empty ``Answer:`` and lets it override an OPEN header."""
    text = _read_text_capped(run_dir / "escalations.md")
    for header, body in _split_escalation_blocks(text):
        token, title, header_state = _parse_escalation_header(header)
        if token is None:
            continue
        state = "ANSWERED" if (header_state == "ANSWERED" or
                               _has_filled_answer(body)) else header_state
        yield token, title, state


def _split_escalation_blocks(text):
    """Yield ``(header_line, [body_lines])`` for each ``## [...]`` block."""
    header, body = None, []
    for line in text.splitlines():
        if line.startswith("## ["):
            if header is not None:
                yield header, body
            header, body = line, []
        elif header is not None:
            body.append(line)
    if header is not None:
        yield header, body


def _parse_escalation_header(line):
    """Return ``(token, title, state)`` for a header, or ``(None, '', '')``."""
    close = line.find("]", 4)
    if close == -1:
        return None, "", ""
    rest = line[close + 1:]
    state = _header_state(rest)
    return line[4:close].strip(), rest.split("(status:")[0].strip(), state


def _header_state(rest):
    """Map the part after the bracket to 'OPEN', 'ANSWERED', or '' (unknown)."""
    if "(status: OPEN)" in rest:
        return "OPEN"
    if "(status: ANSWERED)" in rest:
        return "ANSWERED"
    return ""


def _has_filled_answer(body_lines):
    """True if any body line is a non-empty ``Answer: <text>``."""
    for line in body_lines:
        stripped = line.strip().lstrip("-* ").strip()
        if stripped.lower().startswith("answer:"):
            return bool(stripped[len("answer:"):].strip())
    return False


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
        self._emit(self._route(), write_body=True)

    def do_HEAD(self):
        self._emit(self._route(), write_body=False)

    def _route(self):
        """Dispatch the request to a handler, returning a Response."""
        if not self._host_allowed():
            return _text(421, b"misdirected request")
        route = self.path.split("?", 1)[0]
        if route == "/api/runs":
            return self._serve_api_runs()
        if route.startswith("/api/runs/"):
            return self._serve_api_run_detail(route[len("/api/runs/"):])
        return self._serve_static(route)

    # Any other verb is rejected uniformly.
    def _reject_method(self):
        self._emit(_text(405, b"method not allowed"), write_body=True)

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _reject_method

    # --- security gates ---

    def _host_allowed(self):
        host = self.headers.get("Host")
        return host is not None and host in self.allowed_hosts

    # --- endpoints (each returns a Response) ---

    def _serve_api_runs(self):
        runs = scan_runs(self.data_root)
        etag = _etag("|".join(self._collection_material(runs)))
        return (self._not_modified(etag)
                or _json_response({"runs": runs}, etag))

    def _collection_material(self, runs):
        data_root = Path(self.data_root)
        return [f"{r['run_id']}:{_run_etag(data_root / r['run_id'])}"
                for r in runs]

    def _serve_api_run_detail(self, raw_id):
        run_dir = self._resolve_run_dir(raw_id.rstrip("/"))
        if run_dir is None:
            return _text(404, b"not found")
        etag = _run_etag(Path(run_dir))
        return (self._not_modified(etag)
                or _json_response(_scan_one_run(Path(run_dir)), etag))

    def _resolve_run_dir(self, run_id):
        """Path-traversal-safe: enumerate discovered run dirs, exact-match the
        basename, then realpath-confine. Returns the dir or None (one uniform
        miss for "no such run" and "escapes root" — no path-existence oracle)."""
        known = {Path(p).parent.name for p in
                 glob.glob(str(Path(self.data_root) / "*" / "dag.json"))}
        if run_id not in known:
            return None
        run_dir = resolve_within(self.data_root, run_id)
        return run_dir if run_dir and os.path.isdir(run_dir) else None

    def _serve_static(self, route):
        rel = route.lstrip("/") or "index.html"
        target = resolve_within(self.assets_root, rel)
        if target is None or not os.path.isfile(target):
            return _text(404, b"not found")
        body = self._read_asset(target)
        if body is None:
            return _text(404, b"not found")
        return Response(200, body, _content_type(target))

    def _read_asset(self, target):
        try:
            with open(target, "rb") as fh:
                return fh.read(MAX_FILE_BYTES)
        except OSError:
            return None

    # --- response helpers ---

    def _not_modified(self, etag):
        """Return a 304 Response if the client's If-None-Match matches, else None."""
        if self.headers.get("If-None-Match") == etag:
            return Response(304, b"", "application/json", etag)
        return None

    def _emit(self, resp, write_body):
        self.send_response(resp.status)
        self.send_header("Content-Type", resp.content_type)
        self.send_header("Content-Length", str(len(resp.body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        if resp.etag:
            self.send_header("ETag", resp.etag)
        self.end_headers()
        if write_body and resp.body:
            self.wfile.write(resp.body)

    def log_message(self, *args):
        pass  # quiet by default


def _json_response(obj, etag=None):
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    return Response(200, body, "application/json; charset=utf-8", etag)


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


def main() -> int:
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
