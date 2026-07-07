#!/usr/bin/env python3
"""Deterministic Obsidian knowledge-graph mechanics for the spec-loop plugin.

The ``knowledge-graph`` skill (and, through it, the ``/spec-loop`` controller and
the ``runbook`` skill) uses this module to create / reference / update notes in a
user-supplied Obsidian vault. It is the **single source of truth for the merge
logic** so the LLM never hand-merges markdown: an upsert is idempotent across runs
— a node created by one run is *updated* (not duplicated) by the next.

Design mirrors the plugin's other helpers (``dashboard_server.py`` /
``pr_resolver.py``): **stdlib-only**, pure functions, path-containment guarded, and
unit-tested. No third-party YAML dependency — a tiny frontmatter reader/writer
handles the fixed schema this module emits.

Vault layout (under ``<vault_root>/<subfolder>/``, subfolder defaults to
``spec-loop`` and may be ``""`` to write at the vault root)::

    System/<repo>.md            hub, ONE per repo — grows across every run
    Components/<subsystem>.md    lightweight hubs — link targets
    Decisions/<repo>-<slug>.md   ADR-style, one per material decision
    Patterns/<slug>.md           architecture/design patterns — accumulate
    Domain/<repo>-<slug>.md       business rules / domain logic
    Runs/<run-id>.md              MOC index tying a run's nodes together

Nodes are identified by ``(type, id)``. Edges are Obsidian ``[[wikilinks]]``
rendered by the target node's id (its filename stem).

CLI (used by the skill)::

    python3 knowledge_graph.py batch   < payload.json     # upsert many nodes + MOC
    python3 knowledge_graph.py upsert  --vault ... --type decision --id ... ...
    python3 knowledge_graph.py query   --vault ... [--type ...] [--tag ...] [--term ...]

All commands print a JSON result to stdout and never raise on a per-node problem —
they collect errors so a partial vault write is still reported, keeping the feature
"light touch" (a vault hiccup never blocks the loop).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

# The node types and the vault subdirectory each maps to. Order is stable so the
# emitted layout is deterministic.
TYPE_DIRS = {
    "system": "System",
    "component": "Components",
    "decision": "Decisions",
    "pattern": "Patterns",
    "domain": "Domain",
    "run": "Runs",
}

MAX_FILE_BYTES = 1_000_000  # cap any single note read into memory (mirror dashboard_server)
MAX_SLUG_LEN = 80

# Managed body regions, delimited by HTML comments so upserts can find and rewrite
# them deterministically without disturbing the human-authored summary above them.
_OBS_OPEN, _OBS_CLOSE = "<!-- kg:observations -->", "<!-- /kg:observations -->"
_LINKS_OPEN, _LINKS_CLOSE = "<!-- kg:links -->", "<!-- /kg:links -->"

# Canonical frontmatter key order for stable, diff-friendly output.
_FM_ORDER = ["type", "id", "title", "tags", "repo", "runs",
             "created", "updated", "status", "reversibility"]


# --------------------------------------------------------------------------
# Path safety (mirrors dashboard_server.resolve_within)
# --------------------------------------------------------------------------

def resolve_within(root, relpath):
    """Resolve ``relpath`` under ``root``; return a safe absolute path or ``None``.

    Rejects null bytes and absolute paths, canonicalizes via ``os.path.realpath``
    (collapsing ``..`` and following symlinks), and asserts the result stays under
    ``realpath(root)`` via ``os.path.commonpath`` — so ``..`` traversal, a sibling
    like ``<root>-evil``, or an escaping symlink cannot pass. ``root`` is realpath'd
    too (macOS ``/tmp`` -> ``/private/tmp``).
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
        return None
    return candidate


# --------------------------------------------------------------------------
# Slugs
# --------------------------------------------------------------------------

def slugify(text):
    """Lowercase, ASCII, hyphen-separated slug — stable so ids don't drift."""
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:MAX_SLUG_LEN].strip("-") or "untitled"


# --------------------------------------------------------------------------
# Minimal frontmatter reader / writer (only the fixed schema this module emits)
# --------------------------------------------------------------------------

_NEEDS_QUOTE = re.compile(r'^\s|\s$|[:#\[\]{}"\']|^$')


def _quote_scalar(value):
    s = str(value)
    if _NEEDS_QUOTE.search(s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def _unquote_scalar(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        inner = s[1:-1]
        return inner.replace('\\"', '"').replace("\\\\", "\\")
    return s


def _dump_frontmatter(fm):
    """Serialize a frontmatter dict to a YAML-ish block (no external dep)."""
    keys = [k for k in _FM_ORDER if k in fm] + [k for k in fm if k not in _FM_ORDER]
    lines = []
    for key in keys:
        value = fm[key]
        if isinstance(value, (list, tuple)):
            items = ", ".join(_quote_scalar(v) for v in value)
            lines.append(f"{key}: [{items}]")
        else:
            lines.append(f"{key}: {_quote_scalar(value)}")
    return "\n".join(lines)


def _parse_frontmatter(text):
    """Return ``(fm_dict, body)``. Tolerant: on a note with no/invalid frontmatter
    the whole text becomes the body and ``fm`` is empty, so we never clobber
    hand-edited content."""
    if not text.startswith("---"):
        return {}, text
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.DOTALL)
    if not m:
        return {}, text
    fm = {}
    for line in m.group(1).splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, rest = line.partition(":")
        key, rest = key.strip(), rest.strip()
        if rest.startswith("[") and rest.endswith("]"):
            inner = rest[1:-1].strip()
            fm[key] = [_unquote_scalar(p) for p in _split_inline_list(inner)] if inner else []
        else:
            fm[key] = _unquote_scalar(rest)
    return fm, m.group(2)


def _split_inline_list(inner):
    """Split ``a, "b, c", d`` respecting quotes."""
    parts, buf, quote = [], [], None
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf).strip())
    return [p for p in parts if p]


# --------------------------------------------------------------------------
# Managed body regions
# --------------------------------------------------------------------------

def _extract_region(body, open_tag, close_tag):
    """Return ``(before, inner, after)`` around a managed region, or ``None`` if
    the region isn't present."""
    start = body.find(open_tag)
    if start == -1:
        return None
    end = body.find(close_tag, start)
    if end == -1:
        return None
    inner = body[start + len(open_tag):end]
    return body[:start], inner.strip("\n"), body[end + len(close_tag):]


def _merge_observation(body, run_id, date, note):
    """Append a dated observation block, creating the region if needed."""
    if not note:
        return body
    block = f"### {run_id} — {date}\n\n{note.strip()}"
    region = _extract_region(body, _OBS_OPEN, _OBS_CLOSE)
    if region is None:
        section = f"\n## Observations\n\n{_OBS_OPEN}\n{block}\n{_OBS_CLOSE}\n"
        return body.rstrip("\n") + "\n" + section
    before, inner, after = region
    # Idempotency: don't duplicate an identical block for the same run.
    inner = f"{inner}\n\n{block}".strip("\n") if inner else block
    return f"{before}{_OBS_OPEN}\n{inner}\n{_OBS_CLOSE}{after}"


def _merge_links(body, links):
    """Merge ``[[wikilinks]]`` into the managed Links region, deduped, order-stable."""
    links = [l for l in (links or []) if l]
    region = _extract_region(body, _LINKS_OPEN, _LINKS_CLOSE)
    existing = []
    if region is not None:
        before, inner, after = region
        for line in inner.splitlines():
            m = re.match(r"\s*-\s*(\[\[.+?\]\])\s*$", line)
            if m:
                existing.append(m.group(1))
    else:
        before, after = body.rstrip("\n") + "\n", ""
    seen, ordered = set(), []
    for link in existing + [_wikilink(l) for l in links]:
        if link not in seen:
            seen.add(link)
            ordered.append(link)
    if not ordered:
        return body
    rendered = "\n".join(f"- {l}" for l in ordered)
    section = f"{_LINKS_OPEN}\n{rendered}\n{_LINKS_CLOSE}"
    if region is not None:
        return f"{before}{section}{after}"
    return f"{before}\n## Links\n\n{section}\n"


def _wikilink(target):
    """Normalize a link target to ``[[id]]`` form (accepts a bare id or ``[[id]]``)."""
    target = str(target).strip()
    if target.startswith("[[") and target.endswith("]]"):
        return target
    return f"[[{target}]]"


# --------------------------------------------------------------------------
# Upsert / query / MOC
# --------------------------------------------------------------------------

def _vault_reldir(subfolder, node_type):
    directory = TYPE_DIRS.get(node_type)
    if directory is None:
        raise ValueError(f"unknown node type: {node_type!r}")
    return os.path.join(subfolder, directory) if subfolder else directory


def note_relpath(subfolder, node_type, node_id):
    """Vault-relative path of a node's note (``.md``)."""
    return os.path.join(_vault_reldir(subfolder, node_type), f"{slugify(node_id)}.md")


def _read_note(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(MAX_FILE_BYTES)
    except (OSError, ValueError):
        return None


def upsert_node(vault_root, subfolder, node, run_id, date):
    """Create or idempotently update one node's note.

    ``node`` is a dict: ``{type, id, title, repo?, summary?, observation?,
    links?, status?, reversibility?}``. On an existing note we union ``tags``,
    append ``run_id`` to ``runs`` (deduped), bump ``updated``, append a dated
    observation block, and merge links — never duplicating. Returns
    ``{path, created}``. Raises ``ValueError`` only on an unsafe/invalid target.
    """
    node_type = node["type"]
    node_id = slugify(node["id"])
    relpath = note_relpath(subfolder, node_type, node_id)
    abspath = resolve_within(vault_root, relpath)
    if abspath is None:
        raise ValueError(f"unsafe note path: {relpath!r}")

    repo = node.get("repo") or ""
    existing = _read_note(abspath)
    if existing is not None:
        fm, body = _parse_frontmatter(existing)
        created = fm.get("created", date)
        tags = _dedup(_as_list(fm.get("tags")) + _default_tags(node_type, repo))
        runs = _dedup(_as_list(fm.get("runs")) + [run_id])
        was_created = False
    else:
        fm, body = {}, ""
        created = date
        tags = _default_tags(node_type, repo)
        runs = [run_id]
        summary = node.get("summary") or node.get("title") or node_id
        body = summary.strip() + "\n"
        was_created = True

    fm.update({
        "type": node_type,
        "id": node_id,
        "title": node.get("title") or fm.get("title") or node_id,
        "tags": tags,
        "runs": runs,
        "created": created,
        "updated": date,
    })
    if repo:
        fm["repo"] = repo
    if node.get("status"):
        fm["status"] = node["status"]
    if node.get("reversibility"):
        fm["reversibility"] = node["reversibility"]

    body = _merge_observation(body, run_id, date, node.get("observation"))
    body = _merge_links(body, node.get("links"))

    text = f"---\n{_dump_frontmatter(fm)}\n---\n{body}"
    if not text.endswith("\n"):
        text += "\n"

    os.makedirs(os.path.dirname(abspath), exist_ok=True)
    with open(abspath, "w", encoding="utf-8") as fh:
        fh.write(text)
    return {"path": abspath, "created": was_created}


def _default_tags(node_type, repo):
    tags = ["spec-loop", node_type]
    if repo:
        tags.append(slugify(repo))
    return tags


def _as_list(value):
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _dedup(items):
    seen, out = set(), []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def build_run_moc(vault_root, subfolder, run_id, date, request_title, repo, node_refs):
    """Write/refresh the ``Runs/<run-id>.md`` MOC linking every node the run touched.

    ``node_refs`` is a list of ``{type, id, title}``. The MOC groups links by type
    and back-links the run's artifacts directory. Implemented as an upsert so a
    re-run of the same run-id refreshes rather than duplicates.
    """
    by_type = {}
    for ref in node_refs:
        by_type.setdefault(ref["type"], []).append(ref)
    lines = [f"Knowledge-graph index for spec-loop run `{run_id}`"
             + (f" — {request_title}" if request_title else "") + ".", ""]
    for node_type in TYPE_DIRS:
        refs = by_type.get(node_type)
        if not refs:
            continue
        lines.append(f"## {TYPE_DIRS[node_type]}")
        lines.append("")
        for ref in refs:
            title = ref.get("title") or ref["id"]
            lines.append(f"- [[{slugify(ref['id'])}|{title}]]")
        lines.append("")
    node = {
        "type": "run",
        "id": run_id,
        "title": f"Run {run_id}",
        "repo": repo,
        "summary": "\n".join(lines).strip(),
        "links": [slugify(r["id"]) for r in node_refs],
    }
    return upsert_node(vault_root, subfolder, node, run_id, date)


def query_nodes(vault_root, subfolder, node_type=None, tag=None, term=None):
    """Scan the vault (disk fallback for reference/dedup) and return matching nodes
    as ``{path, id, title, type, tags}``. Used before creating a node to find an
    existing one to update/link instead of duplicating.
    """
    types = [node_type] if node_type else list(TYPE_DIRS)
    results = []
    for nt in types:
        reldir = _vault_reldir(subfolder, nt)
        absdir = resolve_within(vault_root, reldir)
        if not absdir or not os.path.isdir(absdir):
            continue
        for name in sorted(os.listdir(absdir)):
            if not name.endswith(".md"):
                continue
            text = _read_note(os.path.join(absdir, name))
            if text is None:
                continue
            fm, body = _parse_frontmatter(text)
            tags = _as_list(fm.get("tags"))
            if tag and tag not in tags:
                continue
            if term and term.lower() not in text.lower():
                continue
            results.append({
                "path": os.path.join(absdir, name),
                "id": fm.get("id", name[:-3]),
                "title": fm.get("title", name[:-3]),
                "type": fm.get("type", nt),
                "tags": tags,
            })
    return results


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _run_batch(payload):
    """Upsert many nodes and (optionally) a run MOC from one JSON payload::

        {"vault": "...", "subfolder": "spec-loop", "run_id": "...", "date": "...",
         "repo": "...", "nodes": [ {type,id,title,summary,observation,links,
         status,reversibility,repo?}, ... ],
         "moc": true | {"request_title": "..."}}

    Per-node errors are collected, never raised, so a partial write still reports.
    """
    vault = payload["vault"]
    subfolder = payload.get("subfolder", "spec-loop")
    run_id = payload["run_id"]
    date = payload["date"]
    default_repo = payload.get("repo", "")
    results, errors, refs = [], [], []
    for node in payload.get("nodes", []):
        node.setdefault("repo", default_repo)
        try:
            res = upsert_node(vault, subfolder, node, run_id, date)
            results.append({"type": node["type"], "id": slugify(node["id"]),
                            "created": res["created"], "path": res["path"]})
            refs.append({"type": node["type"], "id": node["id"],
                         "title": node.get("title", node["id"])})
        except (ValueError, OSError) as exc:
            errors.append({"node": node.get("id"), "error": str(exc)})
    moc = payload.get("moc")
    if moc:
        request_title = moc.get("request_title", "") if isinstance(moc, dict) else ""
        try:
            build_run_moc(vault, subfolder, run_id, date, request_title, default_repo, refs)
        except (ValueError, OSError) as exc:
            errors.append({"node": f"run:{run_id}", "error": str(exc)})
    return {"upserted": len(results), "created": sum(1 for r in results if r["created"]),
            "updated": sum(1 for r in results if not r["created"]),
            "nodes": results, "errors": errors}


def main(argv=None):
    parser = argparse.ArgumentParser(description="spec-loop Obsidian knowledge-graph helper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_batch = sub.add_parser("batch", help="upsert many nodes + MOC from JSON on stdin")
    p_batch.add_argument("--file", help="read JSON payload from this file instead of stdin")

    p_up = sub.add_parser("upsert", help="upsert a single node")
    p_up.add_argument("--vault", required=True)
    p_up.add_argument("--subfolder", default="spec-loop")
    p_up.add_argument("--type", required=True, choices=list(TYPE_DIRS))
    p_up.add_argument("--id", required=True)
    p_up.add_argument("--title", default="")
    p_up.add_argument("--repo", default="")
    p_up.add_argument("--run", required=True)
    p_up.add_argument("--date", required=True)
    p_up.add_argument("--summary", default="")
    p_up.add_argument("--observation", default="")
    p_up.add_argument("--status", default="")
    p_up.add_argument("--reversibility", default="")
    p_up.add_argument("--link", action="append", default=[], help="repeatable link target id")

    p_q = sub.add_parser("query", help="find existing nodes (for reference/dedup)")
    p_q.add_argument("--vault", required=True)
    p_q.add_argument("--subfolder", default="spec-loop")
    p_q.add_argument("--type", choices=list(TYPE_DIRS))
    p_q.add_argument("--tag")
    p_q.add_argument("--term")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "batch":
            raw = open(args.file, encoding="utf-8").read() if args.file else sys.stdin.read()
            result = _run_batch(json.loads(raw))
        elif args.cmd == "upsert":
            node = {"type": args.type, "id": args.id, "title": args.title,
                    "repo": args.repo, "summary": args.summary,
                    "observation": args.observation, "links": args.link,
                    "status": args.status, "reversibility": args.reversibility}
            res = upsert_node(args.vault, args.subfolder, node, args.run, args.date)
            result = {"created": res["created"], "path": res["path"]}
        else:  # query
            result = {"nodes": query_nodes(args.vault, args.subfolder,
                                           args.type, args.tag, args.term)}
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
