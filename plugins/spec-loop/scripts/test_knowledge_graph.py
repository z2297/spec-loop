#!/usr/bin/env python3
"""Tests for the spec-loop Obsidian knowledge-graph helper (stdlib unittest).

Covers the load-bearing behaviors the skill relies on: idempotent upsert (a
second run *updates* a node rather than duplicating it), frontmatter union,
wikilink dedup, MOC construction, slug stability, and path-traversal refusal —
the guarantee that makes the feature safe to point at a real personal vault.

`scripts/validate_marketplace.py` does NOT lint scripts/*.py, so this is the
sole automated guard on the helper's behavior. Standard library only.

Usage:
    python3 scripts/test_knowledge_graph.py
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import knowledge_graph as kg  # noqa: E402


class TempVault(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = self._tmp.name
        self.subfolder = "spec-loop"

    def tearDown(self):
        self._tmp.cleanup()

    def read(self, node_type, node_id):
        rel = kg.note_relpath(self.subfolder, node_type, node_id)
        return Path(self.vault, rel).read_text(encoding="utf-8")

    def upsert(self, node, run_id, date):
        return kg.upsert_node(self.vault, self.subfolder, node, run_id, date)


# --------------------------------------------------------------------------
# Slugs
# --------------------------------------------------------------------------

class TestSlugify(unittest.TestCase):
    def test_stable_and_ascii(self):
        self.assertEqual(kg.slugify("Deposit Allocation Logic"), "deposit-allocation-logic")
        self.assertEqual(kg.slugify("  Weird__Name!! "), "weird-name")
        self.assertEqual(kg.slugify("A/B & C"), "a-b-c")

    def test_empty_falls_back(self):
        self.assertEqual(kg.slugify(""), "untitled")
        self.assertEqual(kg.slugify("///"), "untitled")

    def test_same_title_same_slug(self):
        self.assertEqual(kg.slugify("Event Bus"), kg.slugify("event bus"))


# --------------------------------------------------------------------------
# Upsert idempotency — the core guarantee
# --------------------------------------------------------------------------

class TestUpsert(TempVault):
    def test_create_then_write(self):
        res = self.upsert({"type": "decision", "id": "use-event-bus",
                           "title": "Use the event bus", "repo": "jobs",
                           "summary": "Allocate deposits via the event bus.",
                           "status": "active", "reversibility": "moderate"},
                          run_id="20260706-a", date="2026-07-06")
        self.assertTrue(res["created"])
        text = self.read("decision", "use-event-bus")
        self.assertIn("type: decision", text)
        self.assertIn("status: active", text)
        self.assertIn("reversibility: moderate", text)
        self.assertIn("runs: [20260706-a]", text)
        self.assertIn("Allocate deposits via the event bus.", text)

    def test_second_run_updates_not_duplicates(self):
        node = {"type": "system", "id": "jobs", "title": "Jobs service",
                "repo": "jobs", "summary": "The jobs service."}
        first = self.upsert(node, run_id="run-1", date="2026-07-01")
        second = self.upsert({**node, "observation": "Added deposit allocation."},
                             run_id="run-2", date="2026-07-06")
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        # Exactly one file exists for this node.
        sysdir = Path(self.vault, self.subfolder, "System")
        self.assertEqual(sorted(p.name for p in sysdir.glob("*.md")), ["jobs.md"])
        text = self.read("system", "jobs")
        # Both runs recorded, created preserved, updated advanced.
        self.assertIn("runs: [run-1, run-2]", text)
        self.assertIn("created: 2026-07-01", text)
        self.assertIn("updated: 2026-07-06", text)
        self.assertIn("Added deposit allocation.", text)
        self.assertIn("### run-2 — 2026-07-06", text)

    def test_run_id_not_duplicated_in_runs(self):
        node = {"type": "pattern", "id": "outbox", "title": "Outbox", "repo": "jobs"}
        self.upsert(node, run_id="run-1", date="2026-07-01")
        self.upsert(node, run_id="run-1", date="2026-07-02")
        text = self.read("pattern", "outbox")
        self.assertIn("runs: [run-1]", text)

    def test_summary_preserved_across_updates(self):
        self.upsert({"type": "domain", "id": "deposit-rules", "repo": "jobs",
                     "summary": "Deposits spread across projects on creation."},
                    run_id="run-1", date="2026-07-01")
        self.upsert({"type": "domain", "id": "deposit-rules", "repo": "jobs",
                     "observation": "Refined via event bus."},
                    run_id="run-2", date="2026-07-06")
        text = self.read("domain", "deposit-rules")
        self.assertIn("Deposits spread across projects on creation.", text)
        self.assertIn("Refined via event bus.", text)

    def test_tags_union_includes_repo(self):
        self.upsert({"type": "decision", "id": "d1", "repo": "jobs", "title": "D1"},
                    run_id="run-1", date="2026-07-01")
        text = self.read("decision", "d1")
        self.assertIn("spec-loop", text)
        self.assertIn("decision", text)
        self.assertIn("jobs", text)


# --------------------------------------------------------------------------
# Wikilinks
# --------------------------------------------------------------------------

class TestLinks(TempVault):
    def test_links_deduped_and_accumulated(self):
        node = {"type": "decision", "id": "d1", "repo": "jobs", "title": "D1",
                "links": ["event-bus", "outbox"]}
        self.upsert(node, run_id="run-1", date="2026-07-01")
        self.upsert({**node, "links": ["outbox", "saga"]},
                    run_id="run-2", date="2026-07-06")
        text = self.read("decision", "d1")
        self.assertEqual(text.count("[[event-bus]]"), 1)
        self.assertEqual(text.count("[[outbox]]"), 1)
        self.assertEqual(text.count("[[saga]]"), 1)

    def test_bare_and_bracketed_targets_normalize(self):
        self.upsert({"type": "decision", "id": "d2", "repo": "jobs", "title": "D2",
                     "links": ["event-bus", "[[event-bus]]"]},
                    run_id="run-1", date="2026-07-01")
        text = self.read("decision", "d2")
        self.assertEqual(text.count("[[event-bus]]"), 1)


# --------------------------------------------------------------------------
# Run MOC
# --------------------------------------------------------------------------

class TestRunMoc(TempVault):
    def test_moc_links_every_node_grouped(self):
        refs = [{"type": "decision", "id": "d1", "title": "Decision one"},
                {"type": "pattern", "id": "outbox", "title": "Outbox pattern"}]
        kg.build_run_moc(self.vault, self.subfolder, "run-1", "2026-07-06",
                         "Add deposits", "jobs", refs)
        text = self.read("run", "run-1")
        self.assertIn("## Decisions", text)
        self.assertIn("## Patterns", text)
        self.assertIn("[[d1|Decision one]]", text)
        self.assertIn("[[outbox|Outbox pattern]]", text)
        self.assertIn("Add deposits", text)


# --------------------------------------------------------------------------
# Frontmatter round-trip
# --------------------------------------------------------------------------

class TestFrontmatter(unittest.TestCase):
    def test_roundtrip_scalars_and_lists(self):
        fm = {"type": "decision", "id": "d1", "title": "Title: with colon",
              "tags": ["spec-loop", "decision"], "runs": ["run-1"]}
        text = f"---\n{kg._dump_frontmatter(fm)}\n---\nbody\n"
        parsed, body = kg._parse_frontmatter(text)
        self.assertEqual(parsed["title"], "Title: with colon")
        self.assertEqual(parsed["tags"], ["spec-loop", "decision"])
        self.assertEqual(parsed["runs"], ["run-1"])
        self.assertEqual(body.strip(), "body")

    def test_note_without_frontmatter_is_all_body(self):
        fm, body = kg._parse_frontmatter("just some prose\n")
        self.assertEqual(fm, {})
        self.assertEqual(body, "just some prose\n")


# --------------------------------------------------------------------------
# Path safety
# --------------------------------------------------------------------------

class TestPathSafety(TempVault):
    def test_traversal_id_neutralized_and_contained(self):
        # slugify strips the traversal *before* it reaches the filesystem, so the
        # write succeeds as a safe in-vault note — and nothing escapes the vault.
        res = self.upsert({"type": "decision", "id": "../../etc/passwd", "repo": "x"},
                          run_id="run-1", date="2026-07-01")
        real_vault = os.path.realpath(self.vault)
        self.assertTrue(os.path.realpath(res["path"]).startswith(real_vault))
        for root, _dirs, files in os.walk(self.vault):
            for name in files:
                self.assertTrue(os.path.realpath(os.path.join(root, name))
                                .startswith(real_vault))

    def test_resolve_within_blocks_escape(self):
        self.assertIsNone(kg.resolve_within(self.vault, "../evil.md"))
        self.assertIsNone(kg.resolve_within(self.vault, "/etc/passwd"))
        self.assertIsNotNone(kg.resolve_within(self.vault, "spec-loop/Decisions/d.md"))

    def test_unknown_type_rejected(self):
        with self.assertRaises(ValueError):
            self.upsert({"type": "bogus", "id": "x"}, run_id="run-1", date="2026-07-01")


# --------------------------------------------------------------------------
# Query + batch CLI path
# --------------------------------------------------------------------------

class TestQueryAndBatch(TempVault):
    def test_query_by_type_and_tag(self):
        self.upsert({"type": "pattern", "id": "outbox", "title": "Outbox", "repo": "jobs"},
                    run_id="run-1", date="2026-07-01")
        self.upsert({"type": "decision", "id": "d1", "title": "D1", "repo": "jobs"},
                    run_id="run-1", date="2026-07-01")
        patterns = kg.query_nodes(self.vault, self.subfolder, node_type="pattern")
        self.assertEqual([n["id"] for n in patterns], ["outbox"])
        jobs = kg.query_nodes(self.vault, self.subfolder, tag="jobs")
        self.assertEqual(sorted(n["id"] for n in jobs), ["d1", "outbox"])

    def test_batch_upserts_and_builds_moc(self):
        payload = {
            "vault": self.vault, "subfolder": self.subfolder,
            "run_id": "run-1", "date": "2026-07-06", "repo": "jobs",
            "nodes": [
                {"type": "system", "id": "jobs", "title": "Jobs"},
                {"type": "decision", "id": "d1", "title": "D1", "links": ["jobs"]},
            ],
            "moc": {"request_title": "Add deposits"},
        }
        result = kg._run_batch(payload)
        self.assertEqual(result["upserted"], 2)
        self.assertEqual(result["created"], 2)
        self.assertEqual(result["errors"], [])
        self.assertTrue(Path(self.vault, self.subfolder, "Runs", "run-1.md").exists())

    def test_batch_collects_errors_without_raising(self):
        payload = {
            "vault": self.vault, "subfolder": self.subfolder,
            "run_id": "run-1", "date": "2026-07-06", "repo": "jobs",
            "nodes": [
                {"type": "system", "id": "jobs", "title": "Jobs"},
                {"type": "bogus", "id": "x", "title": "X"},
            ],
        }
        result = kg._run_batch(payload)
        self.assertEqual(result["upserted"], 1)
        self.assertEqual(len(result["errors"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
