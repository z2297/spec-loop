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
    Reviews/<review-id>.md        ONE per peer review — verdict + P0/P1 titles
    Runs/<run-id>.md              MOC index tying a run's nodes together

Nodes are identified by ``(type, id)``. Edges are Obsidian ``[[wikilinks]]``
rendered by the target node's id (its filename stem).

CLI (used by the skill)::

    python3 knowledge_graph.py batch   < payload.json     # upsert many nodes + MOC
    python3 knowledge_graph.py upsert  --vault ... --type decision --id ... ...
    python3 knowledge_graph.py query   --vault ... [--type ...] [--tag ...] [--term ...] [--run ...]
    python3 knowledge_graph.py context --vault ... --repo ... \
        [--term ...] [--request-file ...] [--component ...]   # prior knowledge, read-only

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
    "review": "Reviews",
    "run": "Runs",
}

MAX_FILE_BYTES = 1_000_000  # cap any single note read into memory (mirror dashboard_server)
MAX_SLUG_LEN = 80

# Managed body regions, delimited by HTML comments so upserts can find and rewrite
# them deterministically without disturbing the human-authored summary above them.
# Observations append, links union, the index is replaced wholesale (a snapshot).
_OBS_OPEN, _OBS_CLOSE = "<!-- kg:observations -->", "<!-- /kg:observations -->"
_LINKS_OPEN, _LINKS_CLOSE = "<!-- kg:links -->", "<!-- /kg:links -->"
_IDX_OPEN, _IDX_CLOSE = "<!-- kg:index -->", "<!-- /kg:index -->"

# Opening prose the pre-kg:index versions of build_run_moc wrote verbatim; used to
# detect and upgrade those stale MOC bodies in place.
_V1_MOC_SENTINEL = "Knowledge-graph index for spec-loop run"

# Canonical frontmatter key order for stable, diff-friendly output.
_FM_ORDER = ["type", "id", "title", "aliases", "tags", "repo", "runs",
             "created", "updated", "status", "reversibility", "verdict"]


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
# Secret redaction — deterministic floor beneath the skill's model-side guard
# --------------------------------------------------------------------------

# Unambiguous token shapes only — no entropy heuristics, since a false positive
# in a personal vault is worse than a conservative floor.
_SECRET_PATTERNS = [
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                       # AWS access key id
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),                    # GitHub classic PAT
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),           # GitHub fine-grained PAT
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),                    # sk-/sk-ant- API keys
    re.compile(r"\bxox[bpsa]-[A-Za-z0-9-]{10,}"),              # Slack tokens
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?"
               r"(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)"),    # PEM private keys
    re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}"
               r"\.[A-Za-z0-9_-]*"),                           # JWTs
]
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization)\b"
    r"(\s*[:=]\s*)(\S{8,})")


def redact_secrets(text):
    """Redact well-known secret shapes to ``[REDACTED]``; return ``(text, count)``.

    The skill's model-side redaction stays the first line of defense (it sees
    context these regexes can't); this is the script-enforced floor applied to
    every field before it reaches the vault.
    """
    if not text:
        return text, 0
    count = 0
    for pattern in _SECRET_PATTERNS:
        text, n = pattern.subn("[REDACTED]", text)
        count += n

    def _assignment(match):
        nonlocal count
        if match.group(3) == "[REDACTED]":
            return match.group(0)
        count += 1
        return f"{match.group(1)}{match.group(2)}[REDACTED]"

    text = _SECRET_ASSIGNMENT.sub(_assignment, text)
    return text, count


# --------------------------------------------------------------------------
# Minimal frontmatter reader / writer (only the fixed schema this module emits)
# --------------------------------------------------------------------------

# Comma is quoted so scalars with commas survive the inline-list round-trip
# (aliases carry human titles, which may contain commas).
_NEEDS_QUOTE = re.compile(r'^\s|\s$|[:#\[\]{}"\',]|^$')


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
    """Append a dated observation block, creating the region if needed.

    Idempotent under retry: an identical block (same run, date, and text) is not
    appended twice, so a re-invoked batch leaves the note byte-identical.
    """
    if not note:
        return body
    block = f"### {run_id} — {date}\n\n{note.strip()}"
    region = _extract_region(body, _OBS_OPEN, _OBS_CLOSE)
    if region is None:
        if block in body:
            return body
        section = f"\n## Observations\n\n{_OBS_OPEN}\n{block}\n{_OBS_CLOSE}\n"
        return body.rstrip("\n") + "\n" + section
    before, inner, after = region
    if block in inner:
        return body
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


def _replace_index(body, rendered):
    """Replace the managed index region wholesale — the index is a snapshot of
    the current state (a run MOC's grouped listing), not an accumulation.

    Bodies written before the region existed carried the rendered index as plain
    prose; those are detected by the exact sentinel they opened with and rebuilt
    as intro line + managed region, preserving any managed sections that follow.
    """
    if not rendered:
        return body
    section = f"{_IDX_OPEN}\n{rendered.strip()}\n{_IDX_CLOSE}"
    region = _extract_region(body, _IDX_OPEN, _IDX_CLOSE)
    if region is not None:
        before, _inner, after = region
        return f"{before}{section}{after}"
    stripped = body.lstrip()
    if stripped.startswith(_V1_MOC_SENTINEL):
        cut = len(body)
        for marker in ("## Links", "## Observations", _LINKS_OPEN, _OBS_OPEN):
            idx = body.find(marker)
            if idx != -1:
                cut = min(cut, idx)
        intro = stripped.splitlines()[0]
        tail = body[cut:].strip("\n")
        text = f"{intro}\n\n{section}\n"
        return text + (f"\n{tail}\n" if tail else "")
    return body.rstrip("\n") + f"\n\n{section}\n"


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
    index?, links?, status?, reversibility?, verdict?}``. On an existing note we union
    ``tags``, append ``run_id`` to ``runs`` (deduped), bump ``updated``, append a
    dated observation block, replace the ``index`` region wholesale, and merge
    links — never duplicating. Returns ``{path, created}``. Raises ``ValueError``
    only on an unsafe/invalid target.
    """
    node_type = node["type"]
    node_id = slugify(node["id"])
    relpath = note_relpath(subfolder, node_type, node_id)
    abspath = resolve_within(vault_root, relpath)
    if abspath is None:
        raise ValueError(f"unsafe note path: {relpath!r}")

    node = dict(node)
    redactions = 0
    for field in ("title", "summary", "observation", "index"):
        if node.get(field):
            node[field], n = redact_secrets(node[field])
            redactions += n

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
    # Alias the human title so [[wikilinks]] by id and the quick switcher both
    # resolve/display it; union preserves user-added aliases, and a title that
    # merely re-slugs to the id adds nothing.
    aliases = _dedup(_as_list(fm.get("aliases"))
                     + ([fm["title"]] if slugify(fm["title"]) != node_id else []))
    if aliases:
        fm["aliases"] = aliases
    if node.get("status"):
        fm["status"] = node["status"]
    if node.get("reversibility"):
        fm["reversibility"] = node["reversibility"]
    if node.get("verdict"):
        fm["verdict"] = node["verdict"]

    body = _replace_index(body, node.get("index"))
    body = _merge_observation(body, run_id, date, node.get("observation"))
    body = _merge_links(body, node.get("links"))

    text = f"---\n{_dump_frontmatter(fm)}\n---\n{body}"
    if not text.endswith("\n"):
        text += "\n"

    os.makedirs(os.path.dirname(abspath), exist_ok=True)
    with open(abspath, "w", encoding="utf-8") as fh:
        fh.write(text)
    return {"path": abspath, "created": was_created, "redactions": redactions}


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


def build_run_moc(vault_root, subfolder, run_id, date, request_title, repo, node_refs,
                  extra_links=None):
    """Write/refresh the ``Runs/<run-id>.md`` MOC linking every node the run touched.

    ``node_refs`` is a list of ``{type, id, title}``. The MOC groups links by type
    inside the managed ``kg:index`` region, which is replaced wholesale on every
    call — so a re-run of the same run-id genuinely refreshes the listing (and a
    pre-region stale body is upgraded in place by ``_replace_index``).
    ``extra_links`` are appended verbatim (not slugified) — used for the run's
    ``.canvas`` companion, whose filename must keep its extension.
    """
    by_type = {}
    for ref in node_refs:
        by_type.setdefault(ref["type"], []).append(ref)
    lines = []
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
        "summary": f"{_V1_MOC_SENTINEL} `{run_id}`"
                   + (f" — {request_title}" if request_title else "") + ".",
        "index": "\n".join(lines).strip(),
        "links": [slugify(r["id"]) for r in node_refs] + list(extra_links or []),
    }
    return upsert_node(vault_root, subfolder, node, run_id, date)


def query_nodes(vault_root, subfolder, node_type=None, tag=None, term=None,
                run_id=None):
    """Scan the vault (disk fallback for reference/dedup) and return matching nodes
    as ``{path, id, title, type, tags}``. Used before creating a node to find an
    existing one to update/link instead of duplicating, and (with ``run_id``) to
    collect every node a run touched.
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
            if run_id and run_id not in _as_list(fm.get("runs")):
                continue
            results.append({
                "path": os.path.join(absdir, name),
                "id": fm.get("id", name[:-3]),
                "title": fm.get("title", name[:-3]),
                "type": fm.get("type", nt),
                "tags": tags,
                "repo": fm.get("repo", ""),
                "status": fm.get("status", ""),
                "created": fm.get("created", ""),
                "updated": fm.get("updated", ""),
                "one_liner": _first_paragraph(body),
            })
    return results


def _first_paragraph(body, limit=200):
    """The note's opening prose — text before any managed region or heading,
    first paragraph only, capped. Used to build the bounded context payload."""
    cut = len(body)
    for marker in (_IDX_OPEN, _OBS_OPEN, _LINKS_OPEN, "\n## "):
        idx = body.find(marker)
        if idx != -1:
            cut = min(cut, idx)
    head = body[:cut].strip()
    return head.split("\n\n", 1)[0].replace("\n", " ").strip()[:limit]


# --------------------------------------------------------------------------
# Context ranking — request-aware lexical relevance (reorders, never filters)
# --------------------------------------------------------------------------

_MAX_TERMS = 64      # boundedness cap on the ranking token set
_COMPONENT_CAP = 5   # per-type cap inside each component context bucket

# Fixed English function words; tokens under 3 chars are dropped anyway, so
# only >= 3-char words need listing. Fixed set keeps ranking deterministic.
_STOPWORDS = frozenset({
    "and", "any", "are", "but", "can", "did", "does", "for", "from", "had",
    "has", "have", "how", "into", "its", "may", "more", "most", "not", "off",
    "other", "our", "out", "over", "shall", "should", "some", "such", "than",
    "that", "the", "their", "them", "then", "there", "these", "they", "this",
    "those", "too", "under", "until", "upon", "was", "were", "what", "when",
    "where", "which", "while", "who", "whose", "why", "will", "with", "would",
    "you", "your",
})

_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")


def _tokenize(text):
    """Lowercase ``[a-z0-9]{3,}`` tokens minus stopwords, first-occurrence
    order, deduped. Deterministic — the ranking's only text treatment."""
    seen, out = set(), []
    for token in _TOKEN_RE.findall((text or "").lower()):
        if token not in _STOPWORDS and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def gather_terms(term_args=(), request_file=None):
    """Union of tokenized ``--term`` values and (optionally) a request file's
    text, deduped preserving first occurrence, capped at ``_MAX_TERMS``.

    Fail-open: a missing/unreadable file contributes nothing — the explicit
    term args still rank. Public so it is unit-testable without the CLI.
    """
    parts = list(term_args or [])
    if request_file:
        try:
            with open(request_file, "r", encoding="utf-8", errors="replace") as fh:
                parts.append(fh.read(MAX_FILE_BYTES))
        except OSError:
            pass
    return _tokenize(" ".join(parts))[:_MAX_TERMS]


def _extract_links(body):
    """``[[target]]`` ids from the managed ``kg:links`` region ONLY — prose
    wikilinks deliberately don't count, keeping component scoping deterministic."""
    region = _extract_region(body, _LINKS_OPEN, _LINKS_CLOSE)
    if region is None:
        return []
    _before, inner, _after = region
    return re.findall(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", inner)


def _observation_text(body):
    """Inner text of the ``kg:observations`` region, ``""`` if absent."""
    region = _extract_region(body, _OBS_OPEN, _OBS_CLOSE)
    return region[1] if region is not None else ""


def _relevance(query_tokens, title, tags, body_text):
    """Weighted lexical overlap: title hits count 3, tag hits 2, body hits 1.
    Pure and deterministic — no corpus statistics, so output never shifts as
    the vault grows."""
    q = set(query_tokens)
    if not q:
        return 0
    return (3 * len(q & set(_tokenize(title)))
            + 2 * len(q & set(_tokenize(" ".join(tags))))
            + len(q & set(_tokenize(body_text))))


def build_context(vault_root, subfolder, repo, limit=10, terms=None,
                  components=None):
    """Read-only prior-knowledge summary for a repo, consumed at run intake.

    Returns a bounded, deterministic dict: the repo's ``system`` hub one-liner;
    ALL ``patterns`` (they are cross-repo by design — the one thing per-repo run
    artifacts cannot carry); ``domain`` notes and non-superseded ``decisions``
    scoped to the repo, newest first, capped at ``limit``; and ``known_ids`` per
    type so callers reuse existing ids instead of drifting into duplicates.

    With ``terms`` (a token list, e.g. from :func:`gather_terms`) entries gain a
    ``relevance`` score and sort by it before recency — ranking **reorders,
    never filters**, so zero-score entries still fill to the cap and an
    off-target term list degrades to the plain newest-first output. With
    ``components`` (slug list) the result gains a ``components`` map of
    per-component buckets — decisions/patterns/domain whose managed links
    include that component, capped at ``_COMPONENT_CAP`` per type — used by the
    controller to give each slice its own scoped prior knowledge.
    """
    repo_slug = slugify(repo) if repo else ""
    terms = list(terms) if terms else []

    def scan(node_type):
        reldir = _vault_reldir(subfolder, node_type)
        absdir = resolve_within(vault_root, reldir)
        if not absdir or not os.path.isdir(absdir):
            return []
        out = []
        for name in sorted(os.listdir(absdir)):
            if not name.endswith(".md"):
                continue
            text = _read_note(os.path.join(absdir, name))
            if text is None:
                continue
            fm, body = _parse_frontmatter(text)
            one_liner = _first_paragraph(body)
            entry = {"id": fm.get("id", name[:-3]),
                     "title": fm.get("title", name[:-3]),
                     "repo": fm.get("repo", ""),
                     "status": fm.get("status", ""),
                     "verdict": fm.get("verdict", ""),
                     "updated": fm.get("updated", ""),
                     "runs": len(_as_list(fm.get("runs"))),
                     "one_liner": one_liner,
                     "links": _extract_links(body)}
            if terms:
                entry["relevance"] = _relevance(
                    terms, entry["title"], _as_list(fm.get("tags")),
                    one_liner + " " + _observation_text(body))
            out.append(entry)
        return out

    def ordered(entries, cap):
        entries = sorted(entries, key=lambda e: e["id"])
        entries.sort(key=lambda e: e["updated"], reverse=True)
        if terms:
            entries.sort(key=lambda e: e["relevance"], reverse=True)
        return entries[:cap]

    def public(entry, extra=()):
        keys = ("id", "title", "one_liner", "runs", "updated") + tuple(extra)
        if terms:
            keys += ("relevance",)
        return {k: entry[k] for k in keys}

    scans = {nt: scan(nt) for nt in ("system", "component", "pattern",
                                     "domain", "decision", "review")}
    for_repo = lambda entries: [e for e in entries  # noqa: E731
                                if not repo_slug or e["repo"] == repo_slug]
    system = next((e for e in scans["system"] if e["id"] == repo_slug), None)
    decisions = [e for e in for_repo(scans["decision"])
                 if e["status"] != "superseded"]
    domain = for_repo(scans["domain"])
    result = {
        "repo": repo_slug,
        "system": system["one_liner"] if system else None,
        "patterns": [public(e) for e in ordered(scans["pattern"], limit)],
        "domain": [public(e) for e in ordered(domain, limit)],
        "decisions": [public(e, extra=("status",))
                      for e in ordered(decisions, limit)],
        # Reviews are repo-scoped and never in known_ids — a review id is unique
        # per review (like a run id), so there is nothing to reuse.
        "reviews": [public(e, extra=("verdict",))
                    for e in ordered(for_repo(scans["review"]), limit)],
        "known_ids": {nt: sorted(e["id"] for e in scans[nt])
                      for nt in ("system", "component", "pattern", "domain")},
    }
    if terms:
        result["terms"] = terms
    if components:
        pools = {"decisions": decisions, "patterns": scans["pattern"],
                 "domain": domain}
        result["components"] = {
            comp: {key: [public(e) for e in
                         ordered([e for e in pool if comp in e["links"]],
                                 _COMPONENT_CAP)]
                   for key, pool in pools.items()}
            for comp in [slugify(c) for c in components]}
    return result


# --------------------------------------------------------------------------
# Obsidian-native UX — starter Bases view + per-repo home index
# --------------------------------------------------------------------------

_BASE_FILENAME = "spec-loop.base"

# A starter Obsidian Bases file (core since ~1.9): table views over the notes
# this module writes. Tag-filtered (not folder-filtered) so it works when
# `subfolder` is "" and survives the user moving the file. Create-once: the
# user owns it after first write.
_BASE_CONTENT = """\
filters:
  and:
    - file.hasTag("spec-loop")
views:
  - type: table
    name: Runs
    filters:
      and:
        - 'note.type == "run"'
    order: [file.name, note.title, note.repo, note.created]
    sort:
      - property: note.created
        direction: DESC
  - type: table
    name: Decisions
    filters:
      and:
        - 'note.type == "decision"'
    order: [file.name, note.title, note.repo, note.status, note.reversibility, note.updated]
    sort:
      - property: note.updated
        direction: DESC
  - type: table
    name: Patterns
    filters:
      and:
        - 'note.type == "pattern"'
    order: [file.name, note.title, note.repo, note.runs, note.updated]
    sort:
      - property: note.updated
        direction: DESC
  - type: table
    name: Domain
    filters:
      and:
        - 'note.type == "domain"'
    order: [file.name, note.title, note.repo, note.updated]
    sort:
      - property: note.updated
        direction: DESC
  - type: table
    name: Reviews
    filters:
      and:
        - 'note.type == "review"'
    order: [file.name, note.title, note.repo, note.verdict, note.updated]
    sort:
      - property: note.updated
        direction: DESC
"""


def write_base_file(vault_root, subfolder):
    """Create the starter ``spec-loop.base`` once; never touch an existing one.

    Bases files have no managed-region mechanism, so create-once-if-absent is
    the only way to honor "never clobber human edits". Returns
    ``{path, created}``; raises ``ValueError`` on an unsafe target.
    """
    rel = os.path.join(subfolder, _BASE_FILENAME) if subfolder else _BASE_FILENAME
    abspath = resolve_within(vault_root, rel)
    if abspath is None:
        raise ValueError(f"unsafe base path: {rel!r}")
    if os.path.exists(abspath):
        return {"path": abspath, "created": False}
    os.makedirs(os.path.dirname(abspath), exist_ok=True)
    with open(abspath, "w", encoding="utf-8") as fh:
        fh.write(_BASE_CONTENT)
    return {"path": abspath, "created": True}


def render_repo_index(vault_root, subfolder, repo, limit=15):
    """Render the per-repo home index for the ``System/<repo>`` hub's managed
    ``kg:index`` region — the entry point a human opens.

    Deterministic snapshot: runs newest-first (by ``created``, cap ``limit``),
    active (non-superseded) decisions, patterns (cross-repo by design), domain
    and reviews for this repo. Empty sections are omitted. Returns ``""`` when
    there is nothing to list.
    """
    repo_slug = slugify(repo) if repo else ""

    def rows(node_type, repo_scoped=True, skip_superseded=False, cap=10,
             by="updated"):
        try:
            found = query_nodes(vault_root, subfolder, node_type=node_type)
        except (ValueError, OSError):
            return []
        if repo_scoped and repo_slug:
            found = [n for n in found if n["repo"] == repo_slug]
        if skip_superseded:
            found = [n for n in found if n["status"] != "superseded"]
        found.sort(key=lambda n: n["id"])
        found.sort(key=lambda n: n[by], reverse=True)
        return [f"- [[{n['id']}|{n['title']}]]" for n in found[:cap]]

    sections = [
        ("Runs", rows("run", cap=limit, by="created")),
        ("Active decisions", rows("decision", skip_superseded=True)),
        ("Patterns", rows("pattern", repo_scoped=False)),
        ("Domain", rows("domain")),
        ("Reviews", rows("review", cap=5)),
    ]
    lines = []
    for heading, items in sections:
        if not items:
            continue
        lines.extend([f"## {heading}", ""])
        lines.extend(items)
        lines.append("")
    return "\n".join(lines).strip()


# JSON Canvas 1.0 (jsoncanvas.org) preset colors by risk tier: 1 → green,
# 2 → yellow, 3 → red; anything else → purple (visibly "unknown").
_TIER_COLORS = {1: "4", 2: "3", 3: "1"}


def layer_slices(slices):
    """Longest-path wave layering over a dag's ``slices`` → ``{id: wave}``.

    Mirrors the controller's wave semantics: a slice's wave is one past its
    deepest dependency. Split parents (``status: "split"``) are excluded —
    their children carry the real edges — and a dep pointing at an excluded or
    unknown id is dropped defensively rather than failing the render.
    """
    active = {s["id"]: s for s in slices
              if s.get("id") and s.get("status") != "split"}
    waves = {}

    def wave(sid, stack=()):
        if sid in waves:
            return waves[sid]
        if sid in stack:  # cycle guard — never recurse forever on a bad dag
            return 0
        deps = [d for d in (active[sid].get("deps") or []) if d in active]
        w = 0 if not deps else max(wave(d, stack + (sid,)) for d in deps) + 1
        waves[sid] = w
        return w

    for sid in sorted(active):
        wave(sid)
    return waves


def build_run_canvas(vault_root, subfolder, run_id, dag):
    """Write ``Runs/<run-id>.canvas`` — a JSON Canvas 1.0 view of the run DAG.

    Deterministic layout: wave columns (``x = wave * 460``), rows sorted by
    slice id, one labeled group per wave, text nodes colored by risk tier,
    dep edges flowing left→right. **Create-once-if-absent**: canvas JSON has
    no managed-region mechanism, so an existing file (the user may have
    rearranged it) is never touched. Returns ``{path, created}``.
    """
    rel = os.path.join(_vault_reldir(subfolder, "run"),
                       f"{slugify(run_id)}.canvas")
    abspath = resolve_within(vault_root, rel)
    if abspath is None:
        raise ValueError(f"unsafe canvas path: {rel!r}")
    if os.path.exists(abspath):
        return {"path": abspath, "created": False}

    slices = [s for s in (dag.get("slices") or [])
              if s.get("id") and s.get("status") != "split"]
    if not slices:
        raise ValueError("dag has no renderable slices")
    waves = layer_slices(dag.get("slices") or [])

    by_wave = {}
    for s in sorted(slices, key=lambda s: s["id"]):
        by_wave.setdefault(waves.get(s["id"], 0), []).append(s)

    nodes, edges = [], []
    for w, members in sorted(by_wave.items()):
        x = w * 460
        for row, s in enumerate(members):
            goal, _n = redact_secrets(str(s.get("goal") or ""))
            goal = goal.replace("\n", " ").strip()[:200]
            tier = s.get("risk_tier")
            status = s.get("status") or "pending"
            text = f"**{s['id']}**" + (f" — {goal}" if goal else "")
            text += f"\n\ntier {tier} · {status}" if tier else f"\n\n{status}"
            nodes.append({"id": f"s-{s['id']}", "type": "text",
                          "x": x, "y": row * 200, "width": 360, "height": 140,
                          "color": _TIER_COLORS.get(tier, "5"), "text": text})
        bottom = (len(members) - 1) * 200 + 140
        nodes.append({"id": f"wave-{w}", "type": "group",
                      "label": f"Wave {w}", "x": x - 20, "y": -40,
                      "width": 400, "height": bottom + 80})

    known = {f"s-{s['id']}" for s in slices}
    for s in sorted(slices, key=lambda s: s["id"]):
        for dep in sorted(s.get("deps") or []):
            if f"s-{dep}" in known:
                edges.append({"id": f"e-{dep}-{s['id']}",
                              "fromNode": f"s-{dep}", "fromSide": "right",
                              "toNode": f"s-{s['id']}", "toSide": "left"})

    os.makedirs(os.path.dirname(abspath), exist_ok=True)
    with open(abspath, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"edges": edges, "nodes": nodes},
                            indent=2, sort_keys=True) + "\n")
    return {"path": abspath, "created": True}


# Node types whose ids must stay stable across runs for accumulation to work —
# the only ones eligible for the conservative id-drift remap below.
_REMAP_TYPES = ("pattern", "component", "system", "domain")


def _find_canonical_id(vault_root, subfolder, node):
    """Conservative id-drift backstop for reference-before-create.

    When a node's exact id has no existing note, look for the ONE existing note
    in the same type dir it plainly meant: same id modulo a ``-<type>`` suffix on
    either side, or a slugified-title match. Zero or multiple candidates →
    ``None`` (create as given — never guess a merge).
    """
    node_type = node["type"]
    node_id = slugify(node["id"])
    title_slug = slugify(node["title"]) if node.get("title") else ""
    try:
        existing = query_nodes(vault_root, subfolder, node_type=node_type)
    except (ValueError, OSError):
        return None

    suffix = f"-{node_type}"

    def strip_suffix(s):
        return s[:-len(suffix)] if s.endswith(suffix) else s

    candidates = set()
    for entry in existing:
        eid = entry["id"]
        if eid == node_id:
            return None  # exact note exists after all — nothing to remap
        match = strip_suffix(eid) == strip_suffix(node_id)
        if not match and title_slug:
            match = title_slug in (eid, slugify(entry.get("title") or ""))
        if match:
            candidates.add(eid)
    return candidates.pop() if len(candidates) == 1 else None


def _collect_run_refs(vault_root, subfolder, run_id):
    """Every non-run node in the vault touched by ``run_id``, as MOC refs.

    Sorted by ``(type, id)`` so repeated MOC builds are deterministic. Returns
    ``[]`` on any scan problem (the caller falls back to in-batch refs).
    """
    try:
        found = query_nodes(vault_root, subfolder, run_id=run_id)
    except (ValueError, OSError):
        return []
    refs = [{"type": n["type"], "id": n["id"], "title": n["title"]}
            for n in found if n["type"] != "run"]
    refs.sort(key=lambda r: (r["type"], r["id"]))
    return refs


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
    nodes = [dict(n) for n in payload.get("nodes", [])]
    # Id-drift backstop: remap a new pattern/component/system/domain id onto the
    # one existing note it plainly meant, and rewrite same-payload links to it.
    id_map, remapped = {}, []
    for node in nodes:
        if node.get("type") in _REMAP_TYPES and node.get("id"):
            node_id = slugify(node["id"])
            try:
                abspath = resolve_within(
                    vault, note_relpath(subfolder, node["type"], node_id))
            except ValueError:
                continue
            if abspath is None or os.path.exists(abspath):
                continue
            canonical = _find_canonical_id(vault, subfolder, node)
            if canonical and canonical != node_id:
                id_map[node_id] = canonical
                remapped.append({"from": node_id, "to": canonical})
                node["id"] = canonical
    if id_map:
        for node in nodes:
            if node.get("links"):
                node["links"] = [id_map.get(slugify(l), l) for l in node["links"]]

    results, errors, refs = [], [], []
    redactions = 0
    for node in nodes:
        node.setdefault("repo", default_repo)
        try:
            res = upsert_node(vault, subfolder, node, run_id, date)
            redactions += res.get("redactions", 0)
            results.append({"type": node["type"], "id": slugify(node["id"]),
                            "created": res["created"], "path": res["path"]})
            refs.append({"type": node["type"], "id": node["id"],
                         "title": node.get("title", node["id"])})
        except (ValueError, OSError) as exc:
            errors.append({"node": node.get("id"), "error": str(exc)})
    # Canvas before the MOC so the MOC can link it. Create-once; a malformed or
    # missing dag file is a collected error, never a raised one.
    canvas_res, canvas_link = None, None
    canvas = payload.get("canvas")
    if canvas:
        try:
            dag_file = canvas.get("dag_file") if isinstance(canvas, dict) else None
            if not dag_file:
                raise ValueError("canvas requires a dag_file path")
            with open(dag_file, "r", encoding="utf-8") as fh:
                dag = json.loads(fh.read(MAX_FILE_BYTES))
            res = build_run_canvas(vault, subfolder, run_id, dag)
            canvas_res = {"created": res["created"]}
            canvas_link = f"{slugify(run_id)}.canvas"
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            errors.append({"node": "canvas", "error": str(exc)})
    moc = payload.get("moc")
    if moc:
        request_title = moc.get("request_title", "") if isinstance(moc, dict) else ""
        # The batch's own nodes are already on disk, so a vault scan yields every
        # node this run touched — including earlier batches (wave boundaries) —
        # not just this payload. Fall back to in-batch refs if the scan fails.
        moc_refs = _collect_run_refs(vault, subfolder, run_id) or refs
        try:
            build_run_moc(vault, subfolder, run_id, date, request_title, default_repo,
                          moc_refs, extra_links=[canvas_link] if canvas_link else None)
        except (ValueError, OSError) as exc:
            errors.append({"node": f"run:{run_id}", "error": str(exc)})
        # Refresh the repo hub's home index at the same two moments the MOC is
        # built (controller Phase 1, runbook Phase 5) — after the MOC write so
        # the run itself is listed. Bookkeeping, not a counted upsert.
        if default_repo:
            try:
                index = render_repo_index(vault, subfolder, default_repo)
                if index:
                    upsert_node(vault, subfolder,
                                {"type": "system", "id": default_repo,
                                 "repo": default_repo, "index": index},
                                run_id, date)
            except (ValueError, OSError) as exc:
                errors.append({"node": f"system:{default_repo}",
                               "error": str(exc)})
    result = {"upserted": len(results),
              "created": sum(1 for r in results if r["created"]),
              "updated": sum(1 for r in results if not r["created"]),
              "redactions": redactions, "remapped": remapped,
              "nodes": results, "errors": errors}
    if payload.get("ensure_base"):
        try:
            result["base"] = {"created": write_base_file(vault, subfolder)["created"]}
        except (ValueError, OSError) as exc:
            errors.append({"node": "base", "error": str(exc)})
    if canvas_res is not None:
        result["canvas"] = canvas_res
    return result


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
    p_up.add_argument("--verdict", default="",
                      help="review verdict (review nodes only by convention)")
    p_up.add_argument("--link", action="append", default=[], help="repeatable link target id")

    p_q = sub.add_parser("query", help="find existing nodes (for reference/dedup)")
    p_q.add_argument("--vault", required=True)
    p_q.add_argument("--subfolder", default="spec-loop")
    p_q.add_argument("--type", choices=list(TYPE_DIRS))
    p_q.add_argument("--tag")
    p_q.add_argument("--term")
    p_q.add_argument("--run", help="only nodes whose frontmatter runs include this run-id")

    p_c = sub.add_parser("context",
                         help="prior-knowledge summary for a repo (read-only)")
    p_c.add_argument("--vault", required=True)
    p_c.add_argument("--subfolder", default="spec-loop")
    p_c.add_argument("--repo", required=True)
    p_c.add_argument("--limit", type=int, default=10)
    p_c.add_argument("--term", action="append", default=[],
                     help="repeatable relevance term — ranks (never filters) results")
    p_c.add_argument("--request-file",
                     help="also rank against this file's text (e.g. request.md)")
    p_c.add_argument("--component", action="append", default=[],
                     help="repeatable component slug — adds a scoped bucket per slug")

    args = parser.parse_args(argv)
    try:
        if args.cmd == "batch":
            raw = open(args.file, encoding="utf-8").read() if args.file else sys.stdin.read()
            result = _run_batch(json.loads(raw))
        elif args.cmd == "upsert":
            node = {"type": args.type, "id": args.id, "title": args.title,
                    "repo": args.repo, "summary": args.summary,
                    "observation": args.observation, "links": args.link,
                    "status": args.status, "reversibility": args.reversibility,
                    "verdict": args.verdict}
            res = upsert_node(args.vault, args.subfolder, node, args.run, args.date)
            result = {"created": res["created"], "path": res["path"]}
        elif args.cmd == "query":
            result = {"nodes": query_nodes(args.vault, args.subfolder,
                                           args.type, args.tag, args.term,
                                           run_id=args.run)}
        else:  # context
            terms = gather_terms(args.term, args.request_file)
            result = build_context(args.vault, args.subfolder, args.repo,
                                   args.limit, terms=terms or None,
                                   components=args.component or None)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
