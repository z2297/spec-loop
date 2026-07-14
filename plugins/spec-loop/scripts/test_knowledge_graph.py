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

    def test_identical_observation_not_duplicated_on_retry(self):
        node = {"type": "decision", "id": "d-retry", "title": "Retry", "repo": "jobs",
                "observation": "Chose the event bus."}
        self.upsert(node, run_id="run-1", date="2026-07-01")
        self.upsert(node, run_id="run-1", date="2026-07-01")
        text = self.read("decision", "d-retry")
        self.assertEqual(text.count("### run-1 — 2026-07-01"), 1)
        self.assertEqual(text.count("Chose the event bus."), 1)

    def test_different_observation_same_run_still_appends(self):
        base = {"type": "decision", "id": "d-waves", "title": "Waves", "repo": "jobs"}
        self.upsert({**base, "observation": "Wave 1: first."},
                    run_id="run-1", date="2026-07-01")
        self.upsert({**base, "observation": "Wave 2: second."},
                    run_id="run-1", date="2026-07-01")
        text = self.read("decision", "d-waves")
        self.assertIn("Wave 1: first.", text)
        self.assertIn("Wave 2: second.", text)

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

    def test_moc_body_refreshes_with_superset_refs(self):
        refs = [{"type": "decision", "id": "d1", "title": "Decision one"}]
        kg.build_run_moc(self.vault, self.subfolder, "run-1", "2026-07-01",
                         "Add deposits", "jobs", refs)
        refs.append({"type": "pattern", "id": "outbox", "title": "Outbox pattern"})
        kg.build_run_moc(self.vault, self.subfolder, "run-1", "2026-07-06",
                         "Add deposits", "jobs", refs)
        text = self.read("run", "run-1")
        self.assertEqual(text.count("[[d1|Decision one]]"), 1)
        self.assertEqual(text.count("[[outbox|Outbox pattern]]"), 1)
        self.assertEqual(text.count("## Decisions"), 1)
        self.assertEqual(text.count("## Patterns"), 1)

    def test_legacy_v1_moc_body_upgraded_in_place(self):
        # A pre-kg:index MOC: grouped listing as plain prose, then a Links region.
        rel = kg.note_relpath(self.subfolder, "run", "run-old")
        path = Path(self.vault, rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\ntype: run\nid: run-old\ntitle: Run run-old\n"
            "tags: [spec-loop, run]\nruns: [run-old]\n"
            "created: 2026-07-01\nupdated: 2026-07-01\n---\n"
            "Knowledge-graph index for spec-loop run `run-old` — Old request.\n\n"
            "## Decisions\n\n- [[stale|Stale decision]]\n\n"
            "## Links\n\n<!-- kg:links -->\n- [[stale]]\n<!-- /kg:links -->\n",
            encoding="utf-8")
        refs = [{"type": "decision", "id": "fresh", "title": "Fresh decision"}]
        kg.build_run_moc(self.vault, self.subfolder, "run-old", "2026-07-06",
                         "Old request", "jobs", refs)
        text = self.read("run", "run-old")
        # Stale prose listing replaced by the managed region; links accumulate.
        self.assertIn("<!-- kg:index -->", text)
        self.assertIn("[[fresh|Fresh decision]]", text)
        self.assertNotIn("[[stale|Stale decision]]", text)
        self.assertIn("- [[stale]]", text)  # Links region untouched
        self.assertIn("Knowledge-graph index for spec-loop run `run-old`", text)
        self.assertEqual(text.count("## Decisions"), 1)

    def test_non_run_note_body_untouched_without_index(self):
        self.upsert({"type": "pattern", "id": "outbox", "title": "Outbox",
                     "summary": "Knowledge lives in prose the model wrote."},
                    run_id="run-1", date="2026-07-01")
        before = self.read("pattern", "outbox")
        self.upsert({"type": "pattern", "id": "outbox", "title": "Outbox"},
                    run_id="run-1", date="2026-07-01")
        self.assertEqual(before, self.read("pattern", "outbox"))
        self.assertNotIn("<!-- kg:index -->", before)


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
# Secret redaction — the deterministic floor
# --------------------------------------------------------------------------

class TestRedaction(TempVault):
    def test_known_token_shapes_redacted(self):
        obs = ("Configured with ghp_" + "a" * 36
               + " and password=hunter2secret for the smoke test.")
        res = self.upsert({"type": "decision", "id": "d-sec", "title": "Sec",
                           "repo": "jobs", "observation": obs},
                          run_id="run-1", date="2026-07-01")
        text = self.read("decision", "d-sec")
        self.assertNotIn("ghp_", text)
        self.assertNotIn("hunter2secret", text)
        self.assertIn("[REDACTED]", text)
        self.assertEqual(res["redactions"], 2)

    def test_key_shapes_and_jwt_redacted(self):
        text, count = kg.redact_secrets(
            "AKIAABCDEFGHIJKLMNOP then sk-" + "x" * 24
            + " then eyJ" + "h" * 24 + "." + "p" * 16 + ".sig"
            + " then xoxb-1234567890-abcdef")
        self.assertEqual(count, 4)
        self.assertNotIn("AKIA", text)
        self.assertNotIn("sk-", text)
        self.assertNotIn("eyJ", text)
        self.assertNotIn("xoxb", text)

    def test_pem_block_redacted(self):
        text, count = kg.redact_secrets(
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEow…\n-----END RSA PRIVATE KEY-----")
        self.assertEqual(count, 1)
        self.assertNotIn("MIIEow", text)

    def test_benign_prose_untouched(self):
        prose = ("The token refresh flow rotates the api key nightly; "
                 "no secret leaves the vault.")
        text, count = kg.redact_secrets(prose)
        self.assertEqual(count, 0)
        self.assertEqual(text, prose)

    def test_batch_reports_redaction_count(self):
        result = kg._run_batch({
            "vault": self.vault, "subfolder": self.subfolder,
            "run_id": "run-1", "date": "2026-07-01", "repo": "jobs",
            "nodes": [{"type": "decision", "id": "d1", "title": "D1",
                       "observation": "api_key=abcdefgh12345678 was rotated."}],
        })
        self.assertEqual(result["redactions"], 1)
        self.assertNotIn("abcdefgh12345678", self.read("decision", "d1"))


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

    def test_query_run_filter(self):
        self.upsert({"type": "decision", "id": "d1", "title": "D1", "repo": "jobs"},
                    run_id="run-1", date="2026-07-01")
        self.upsert({"type": "decision", "id": "d2", "title": "D2", "repo": "jobs"},
                    run_id="run-2", date="2026-07-02")
        found = kg.query_nodes(self.vault, self.subfolder, run_id="run-1")
        self.assertEqual([n["id"] for n in found], ["d1"])

    def test_moc_includes_nodes_from_earlier_batches(self):
        # Wave-boundary batch: decisions, no MOC.
        kg._run_batch({
            "vault": self.vault, "subfolder": self.subfolder,
            "run_id": "run-1", "date": "2026-07-01", "repo": "jobs",
            "nodes": [{"type": "decision", "id": "d1", "title": "D1"},
                      {"type": "decision", "id": "d2", "title": "D2"}],
        })
        # Runbook batch: one pattern, MOC finalized.
        result = kg._run_batch({
            "vault": self.vault, "subfolder": self.subfolder,
            "run_id": "run-1", "date": "2026-07-06", "repo": "jobs",
            "nodes": [{"type": "pattern", "id": "outbox", "title": "Outbox"}],
            "moc": {"request_title": "Add deposits"},
        })
        self.assertEqual(result["errors"], [])
        text = self.read("run", "run-1")
        for link in ("[[d1|D1]]", "[[d2|D2]]", "[[outbox|Outbox]]"):
            self.assertIn(link, text)

    def test_batch_retry_is_byte_identical(self):
        payload = {
            "vault": self.vault, "subfolder": self.subfolder,
            "run_id": "run-1", "date": "2026-07-06", "repo": "jobs",
            "nodes": [
                {"type": "system", "id": "jobs", "title": "Jobs",
                 "summary": "The jobs service.",
                 "observation": "Seeded by run-1."},
                {"type": "decision", "id": "d1", "title": "D1",
                 "observation": "Wave 1: chose the event bus.",
                 "links": ["jobs"]},
            ],
            "moc": {"request_title": "Add deposits"},
        }
        def snapshot():
            files = {}
            for root, _dirs, names in os.walk(self.vault):
                for name in sorted(names):
                    p = Path(root, name)
                    files[str(p.relative_to(self.vault))] = p.read_bytes()
            return files
        kg._run_batch(payload)
        first = snapshot()
        kg._run_batch(payload)
        self.assertEqual(first, snapshot())

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


# --------------------------------------------------------------------------
# Context — the read path consumed at run intake
# --------------------------------------------------------------------------

class TestBuildContext(TempVault):
    def seed(self):
        self.upsert({"type": "system", "id": "repo-a", "title": "Repo A",
                     "summary": "Service A owns deposits."},
                    run_id="run-1", date="2026-07-01")
        self.upsert({"type": "pattern", "id": "outbox", "title": "Outbox",
                     "summary": "Transactional outbox.", "repo": "repo-b"},
                    run_id="run-0", date="2026-06-01")
        self.upsert({"type": "domain", "id": "repo-a-deposits", "repo": "repo-a",
                     "title": "Deposit rules", "summary": "Deposits spread evenly."},
                    run_id="run-1", date="2026-07-01")
        self.upsert({"type": "decision", "id": "d-active", "repo": "repo-a",
                     "title": "Active", "status": "active"},
                    run_id="run-1", date="2026-07-01")
        self.upsert({"type": "decision", "id": "d-old", "repo": "repo-a",
                     "title": "Old", "status": "superseded"},
                    run_id="run-1", date="2026-07-01")
        self.upsert({"type": "decision", "id": "d-other", "repo": "repo-b",
                     "title": "Other"},
                    run_id="run-1", date="2026-07-01")

    def test_context_scopes_and_filters(self):
        self.seed()
        ctx = kg.build_context(self.vault, self.subfolder, "repo-a")
        self.assertEqual(ctx["system"], "Service A owns deposits.")
        # Patterns are cross-repo — repo-b's pattern still surfaces for repo-a.
        self.assertEqual([p["id"] for p in ctx["patterns"]], ["outbox"])
        self.assertEqual([d["id"] for d in ctx["domain"]], ["repo-a-deposits"])
        # Superseded and other-repo decisions excluded.
        self.assertEqual([d["id"] for d in ctx["decisions"]], ["d-active"])
        self.assertEqual(ctx["known_ids"]["pattern"], ["outbox"])
        self.assertEqual(ctx["known_ids"]["system"], ["repo-a"])

    def test_context_on_empty_vault_is_well_formed(self):
        ctx = kg.build_context(self.vault, self.subfolder, "repo-a")
        self.assertIsNone(ctx["system"])
        self.assertEqual(ctx["patterns"], [])
        self.assertEqual(ctx["decisions"], [])
        self.assertEqual(ctx["known_ids"]["pattern"], [])

    def test_context_caps_and_orders_newest_first(self):
        for i in range(5):
            self.upsert({"type": "decision", "id": f"d{i}", "repo": "repo-a",
                         "title": f"D{i}"},
                        run_id=f"run-{i}", date=f"2026-07-0{i + 1}")
        ctx = kg.build_context(self.vault, self.subfolder, "repo-a", limit=3)
        self.assertEqual([d["id"] for d in ctx["decisions"]], ["d4", "d3", "d2"])


# --------------------------------------------------------------------------
# Context ranking — request-aware relevance (reorders, never filters)
# --------------------------------------------------------------------------

class TestContextRanking(TempVault):
    def seed(self):
        self.upsert({"type": "system", "id": "repo-a", "title": "Repo A",
                     "summary": "Service A owns deposits."},
                    run_id="run-1", date="2026-07-01")
        self.upsert({"type": "decision", "id": "d-bus", "repo": "repo-a",
                     "title": "Use the event bus",
                     "summary": "Allocate via the event bus."},
                    run_id="run-1", date="2026-07-01")
        self.upsert({"type": "decision", "id": "d-newer", "repo": "repo-a",
                     "title": "Retention policy",
                     "summary": "Keep records ninety days."},
                    run_id="run-2", date="2026-07-06")

    def test_no_terms_output_unchanged(self):
        # Backward-compat pin: without terms/components the payload carries
        # exactly the pre-ranking keys — no relevance, no terms echo, no buckets.
        self.seed()
        ctx = kg.build_context(self.vault, self.subfolder, "repo-a")
        self.assertNotIn("terms", ctx)
        self.assertNotIn("components", ctx)
        for entry in ctx["decisions"]:
            self.assertEqual(sorted(entry),
                             ["id", "one_liner", "runs", "status", "title",
                              "updated"])
        # Newest-first ordering intact.
        self.assertEqual([d["id"] for d in ctx["decisions"]],
                         ["d-newer", "d-bus"])

    def test_title_match_outranks_recency(self):
        self.seed()
        ctx = kg.build_context(self.vault, self.subfolder, "repo-a",
                               terms=["event", "bus"])
        self.assertEqual(ctx["decisions"][0]["id"], "d-bus")
        self.assertGreater(ctx["decisions"][0]["relevance"], 0)
        self.assertEqual(ctx["terms"], ["event", "bus"])

    def test_title_weighting_beats_body_match(self):
        self.upsert({"type": "decision", "id": "d-title", "repo": "repo-a",
                     "title": "Outbox strategy", "summary": "A choice."},
                    run_id="run-1", date="2026-07-01")
        self.upsert({"type": "decision", "id": "d-body", "repo": "repo-a",
                     "title": "Messaging", "summary": "Uses the outbox table."},
                    run_id="run-2", date="2026-07-06")
        ctx = kg.build_context(self.vault, self.subfolder, "repo-a",
                               terms=["outbox"])
        self.assertEqual([d["id"] for d in ctx["decisions"]],
                         ["d-title", "d-body"])
        self.assertGreater(ctx["decisions"][0]["relevance"],
                           ctx["decisions"][1]["relevance"])

    def test_observation_text_is_scored(self):
        self.upsert({"type": "decision", "id": "d-obs", "repo": "repo-a",
                     "title": "Plain", "summary": "Nothing here.",
                     "observation": "Refined the saga compensation flow."},
                    run_id="run-1", date="2026-07-01")
        ctx = kg.build_context(self.vault, self.subfolder, "repo-a",
                               terms=["saga", "compensation"])
        self.assertEqual(ctx["decisions"][0]["id"], "d-obs")
        self.assertGreater(ctx["decisions"][0]["relevance"], 0)

    def test_zero_score_entries_still_fill_to_limit(self):
        # Ranking reorders, never filters — the recency floor survives.
        self.seed()
        ctx = kg.build_context(self.vault, self.subfolder, "repo-a",
                               terms=["zzzunmatched"])
        self.assertEqual(len(ctx["decisions"]), 2)
        for entry in ctx["decisions"]:
            self.assertEqual(entry["relevance"], 0)
        # All zero → recency order.
        self.assertEqual([d["id"] for d in ctx["decisions"]],
                         ["d-newer", "d-bus"])

    def test_tie_breaks_deterministic(self):
        self.upsert({"type": "decision", "id": "d-b", "repo": "repo-a",
                     "title": "Same day B"}, run_id="run-1", date="2026-07-01")
        self.upsert({"type": "decision", "id": "d-a", "repo": "repo-a",
                     "title": "Same day A"}, run_id="run-1", date="2026-07-01")
        ctx = kg.build_context(self.vault, self.subfolder, "repo-a",
                               terms=["zzzunmatched"])
        # Equal relevance, equal updated → id ascending.
        self.assertEqual([d["id"] for d in ctx["decisions"]], ["d-a", "d-b"])

    def test_stopwords_and_short_tokens_ignored(self):
        tokens = kg._tokenize("The use of an ID is not what we want")
        self.assertNotIn("the", tokens)
        self.assertNotIn("not", tokens)
        self.assertNotIn("id", tokens)   # < 3 chars
        self.assertIn("want", tokens)

    def test_gather_terms_from_file_and_args(self):
        req = Path(self.vault, "request.md")
        req.write_text("Migrate the deposit allocation to the event bus",
                       encoding="utf-8")
        terms = kg.gather_terms(["outbox saga"], str(req))
        self.assertIn("outbox", terms)
        self.assertIn("saga", terms)
        self.assertIn("deposit", terms)
        self.assertNotIn("the", terms)
        # Missing file falls back to the args alone (fail-open).
        self.assertEqual(kg.gather_terms(["outbox"], "/nonexistent/x.md"),
                         ["outbox"])
        self.assertLessEqual(
            len(kg.gather_terms(["t" + str(i) * 3 for i in range(100)], None)),
            kg._MAX_TERMS)

    def test_relevance_field_only_with_terms(self):
        self.seed()
        with_terms = kg.build_context(self.vault, self.subfolder, "repo-a",
                                      terms=["event"])
        without = kg.build_context(self.vault, self.subfolder, "repo-a")
        self.assertIn("relevance", with_terms["decisions"][0])
        self.assertNotIn("relevance", without["decisions"][0])


# --------------------------------------------------------------------------
# Component-scoped context — per-slice prior knowledge buckets
# --------------------------------------------------------------------------

class TestComponentContext(TempVault):
    def seed(self):
        self.upsert({"type": "component", "id": "auth-service",
                     "title": "Auth service"},
                    run_id="run-1", date="2026-07-01")
        self.upsert({"type": "decision", "id": "d-auth", "repo": "repo-a",
                     "title": "JWT everywhere", "links": ["auth-service"]},
                    run_id="run-1", date="2026-07-01")
        self.upsert({"type": "pattern", "id": "token-refresh", "repo": "repo-b",
                     "title": "Token refresh", "links": ["auth-service"]},
                    run_id="run-1", date="2026-07-01")
        self.upsert({"type": "domain", "id": "repo-a-billing", "repo": "repo-a",
                     "title": "Billing rules", "links": ["billing"]},
                    run_id="run-1", date="2026-07-01")

    def test_component_bucket_lists_linked_nodes(self):
        self.seed()
        ctx = kg.build_context(self.vault, self.subfolder, "repo-a",
                               components=["auth-service"])
        bucket = ctx["components"]["auth-service"]
        self.assertEqual([d["id"] for d in bucket["decisions"]], ["d-auth"])
        self.assertEqual([p["id"] for p in bucket["patterns"]],
                         ["token-refresh"])
        self.assertEqual(bucket["domain"], [])

    def test_component_bucket_respects_repo_scope_and_supersession(self):
        self.seed()
        self.upsert({"type": "decision", "id": "d-super", "repo": "repo-a",
                     "title": "Old auth", "status": "superseded",
                     "links": ["auth-service"]},
                    run_id="run-1", date="2026-07-01")
        self.upsert({"type": "decision", "id": "d-other-repo", "repo": "repo-b",
                     "title": "Their auth", "links": ["auth-service"]},
                    run_id="run-1", date="2026-07-01")
        ctx = kg.build_context(self.vault, self.subfolder, "repo-a",
                               components=["auth-service"])
        ids = [d["id"] for d in ctx["components"]["auth-service"]["decisions"]]
        self.assertNotIn("d-super", ids)
        self.assertNotIn("d-other-repo", ids)
        # Cross-repo patterns still surface (patterns are cross-repo by design).
        self.assertEqual([p["id"] for p in
                          ctx["components"]["auth-service"]["patterns"]],
                         ["token-refresh"])

    def test_prose_wikilinks_do_not_count(self):
        rel = kg.note_relpath(self.subfolder, "decision", "d-prose")
        path = Path(self.vault, rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\ntype: decision\nid: d-prose\ntitle: Prose link\n"
            "tags: [spec-loop, decision, repo-a]\nrepo: repo-a\n"
            "runs: [run-1]\ncreated: 2026-07-01\nupdated: 2026-07-01\n---\n"
            "Mentions [[auth-service]] in prose only.\n",
            encoding="utf-8")
        ctx = kg.build_context(self.vault, self.subfolder, "repo-a",
                               components=["auth-service"])
        self.assertEqual(ctx["components"]["auth-service"]["decisions"], [])

    def test_unknown_component_yields_empty_bucket(self):
        self.seed()
        ctx = kg.build_context(self.vault, self.subfolder, "repo-a",
                               components=["no-such-thing"])
        self.assertEqual(ctx["components"]["no-such-thing"],
                         {"decisions": [], "patterns": [], "domain": []})
        # And no components key at all when the arg is absent.
        self.assertNotIn("components",
                         kg.build_context(self.vault, self.subfolder, "repo-a"))

    def test_component_bucket_capped(self):
        self.seed()
        for i in range(7):
            self.upsert({"type": "decision", "id": f"d-cap-{i}", "repo": "repo-a",
                         "title": f"Cap {i}", "links": ["auth-service"]},
                        run_id="run-1", date=f"2026-07-0{i + 1}")
        ctx = kg.build_context(self.vault, self.subfolder, "repo-a",
                               components=["auth-service"])
        self.assertEqual(
            len(ctx["components"]["auth-service"]["decisions"]),
            kg._COMPONENT_CAP)


# --------------------------------------------------------------------------
# Id-drift remap — mechanical reference-before-create
# --------------------------------------------------------------------------

class TestIdRemap(TempVault):
    def test_suffixed_id_remaps_to_existing_note(self):
        self.upsert({"type": "pattern", "id": "outbox", "title": "Outbox",
                     "summary": "Transactional outbox."},
                    run_id="run-1", date="2026-07-01")
        result = kg._run_batch({
            "vault": self.vault, "subfolder": self.subfolder,
            "run_id": "run-2", "date": "2026-07-06", "repo": "jobs",
            "nodes": [
                {"type": "pattern", "id": "outbox-pattern", "title": "Outbox",
                 "observation": "Reused for deposits."},
                {"type": "decision", "id": "d1", "title": "D1",
                 "links": ["outbox-pattern"]},
            ],
        })
        self.assertEqual(result["remapped"], [{"from": "outbox-pattern",
                                               "to": "outbox"}])
        patterns = Path(self.vault, self.subfolder, "Patterns")
        self.assertEqual(sorted(p.name for p in patterns.glob("*.md")),
                         ["outbox.md"])
        self.assertIn("Reused for deposits.", self.read("pattern", "outbox"))
        # The same-payload link was rewritten to the canonical id.
        self.assertIn("[[outbox]]", self.read("decision", "d1"))

    def test_new_pattern_is_not_remapped(self):
        self.upsert({"type": "pattern", "id": "outbox", "title": "Outbox"},
                    run_id="run-1", date="2026-07-01")
        result = kg._run_batch({
            "vault": self.vault, "subfolder": self.subfolder,
            "run_id": "run-2", "date": "2026-07-06", "repo": "jobs",
            "nodes": [{"type": "pattern", "id": "saga", "title": "Saga"}],
        })
        self.assertEqual(result["remapped"], [])
        self.assertTrue(Path(self.vault, self.subfolder, "Patterns",
                             "saga.md").exists())

    def test_ambiguous_match_is_not_remapped(self):
        # Two plausible canonical targets → never guess.
        self.upsert({"type": "pattern", "id": "outbox", "title": "Event relay"},
                    run_id="run-1", date="2026-07-01")
        self.upsert({"type": "pattern", "id": "outbox-pattern-v2",
                     "title": "Outbox"},
                    run_id="run-1", date="2026-07-01")
        result = kg._run_batch({
            "vault": self.vault, "subfolder": self.subfolder,
            "run_id": "run-2", "date": "2026-07-06", "repo": "jobs",
            "nodes": [{"type": "pattern", "id": "outbox-pattern",
                       "title": "Outbox"}],
        })
        self.assertEqual(result["remapped"], [])
        self.assertTrue(Path(self.vault, self.subfolder, "Patterns",
                             "outbox-pattern.md").exists())


# --------------------------------------------------------------------------
# Review nodes — the peer-review capture surface
# --------------------------------------------------------------------------

class TestReviewNodes(TempVault):
    REVIEW_ID = "github-acme-pr482-9f3a1c2"

    def review_payload(self, **overrides):
        payload = {
            "vault": self.vault, "subfolder": self.subfolder,
            "run_id": self.REVIEW_ID, "date": "2026-07-14", "repo": "repo-a",
            "nodes": [
                {"type": "review", "id": self.REVIEW_ID,
                 "title": "PR review acme#482: REQUEST_CHANGES",
                 "verdict": "REQUEST_CHANGES",
                 "summary": "repo-a PR 482 reviewed: request changes.",
                 "observation": "P0: 1, P1: 2. Titles: auth bypass on refresh; "
                                "missing rate limit; stale cache on logout.",
                 "links": ["repo-a"]},
                {"type": "system", "id": "repo-a", "title": "Repo A"},
            ],
        }
        payload.update(overrides)
        return payload

    def test_review_node_lands_in_reviews_dir_with_verdict(self):
        result = kg._run_batch(self.review_payload())
        self.assertEqual(result["errors"], [])
        text = self.read("review", self.REVIEW_ID)
        self.assertIn("type: review", text)
        self.assertIn("verdict: REQUEST_CHANGES", text)
        self.assertIn("tags: [spec-loop, review, repo-a]", text)
        self.assertTrue(Path(self.vault, self.subfolder, "Reviews",
                             f"{self.REVIEW_ID}.md").exists())

    def test_verdict_absent_when_not_provided(self):
        self.upsert({"type": "decision", "id": "d1", "repo": "repo-a",
                     "title": "D1"}, run_id="run-1", date="2026-07-01")
        self.assertNotIn("verdict:", self.read("decision", "d1"))

    def test_batch_with_review_id_appends_to_system_hub_runs(self):
        self.upsert({"type": "system", "id": "repo-a", "title": "Repo A",
                     "summary": "Service A."}, run_id="run-1", date="2026-07-01")
        kg._run_batch(self.review_payload())
        text = self.read("system", "repo-a")
        self.assertIn(f"runs: [run-1, {self.REVIEW_ID}]", text)

    def test_review_batch_retry_byte_identical(self):
        def snapshot():
            files = {}
            for root, _dirs, names in os.walk(self.vault):
                for name in sorted(names):
                    p = Path(root, name)
                    files[str(p.relative_to(self.vault))] = p.read_bytes()
            return files
        kg._run_batch(self.review_payload())
        first = snapshot()
        kg._run_batch(self.review_payload())
        self.assertEqual(first, snapshot())

    def test_review_batch_omits_moc(self):
        kg._run_batch(self.review_payload())
        self.assertFalse(Path(self.vault, self.subfolder, "Runs").exists())

    def test_review_type_not_remap_eligible(self):
        # A near-miss review id must create a new note, never remap onto an
        # existing review — review ids are unique per review, like run ids.
        kg._run_batch(self.review_payload())
        near_miss = self.REVIEW_ID + "-review"
        result = kg._run_batch(self.review_payload(
            run_id=near_miss,
            nodes=[{"type": "review", "id": near_miss,
                    "title": "PR review acme#482: APPROVE",
                    "verdict": "APPROVE"}]))
        self.assertEqual(result["remapped"], [])
        reviews = Path(self.vault, self.subfolder, "Reviews")
        self.assertEqual(len(list(reviews.glob("*.md"))), 2)

    def test_context_includes_repo_scoped_reviews_capped(self):
        kg._run_batch(self.review_payload())
        kg._run_batch(self.review_payload(
            run_id="rev-other", repo="repo-b",
            nodes=[{"type": "review", "id": "rev-other",
                    "title": "Other repo review", "verdict": "APPROVE"}]))
        ctx = kg.build_context(self.vault, self.subfolder, "repo-a")
        self.assertEqual([r["id"] for r in ctx["reviews"]], [self.REVIEW_ID])
        self.assertEqual(ctx["reviews"][0]["verdict"], "REQUEST_CHANGES")
        self.assertNotIn("review", ctx["known_ids"])
        # Cap respected.
        for i in range(12):
            kg._run_batch(self.review_payload(
                run_id=f"rev-{i:02d}",
                nodes=[{"type": "review", "id": f"rev-{i:02d}",
                        "title": f"Review {i}", "verdict": "APPROVE",
                        "repo": "repo-a"}]))
        ctx = kg.build_context(self.vault, self.subfolder, "repo-a", limit=10)
        self.assertEqual(len(ctx["reviews"]), 10)

    def test_context_reviews_empty_vault_well_formed(self):
        ctx = kg.build_context(self.vault, self.subfolder, "repo-a")
        self.assertEqual(ctx["reviews"], [])

    def test_query_results_carry_one_liner(self):
        self.upsert({"type": "pattern", "id": "outbox", "title": "Outbox",
                     "summary": "Transactional outbox for exactly-once."},
                    run_id="run-1", date="2026-07-01")
        found = kg.query_nodes(self.vault, self.subfolder, node_type="pattern")
        self.assertEqual(found[0]["one_liner"],
                         "Transactional outbox for exactly-once.")

    def test_review_observation_secret_redacted(self):
        result = kg._run_batch(self.review_payload(
            nodes=[{"type": "review", "id": self.REVIEW_ID,
                    "title": "PR review", "verdict": "APPROVE",
                    "observation": "P0: token=abcdefgh12345678 leaked in config."}]))
        self.assertEqual(result["redactions"], 1)
        self.assertNotIn("abcdefgh12345678", self.read("review", self.REVIEW_ID))


# --------------------------------------------------------------------------
# Aliases — wikilinks and quick-switcher resolve by human title
# --------------------------------------------------------------------------

class TestAliases(TempVault):
    def test_alias_added_when_title_differs_from_slug(self):
        self.upsert({"type": "decision", "id": "d-bus", "repo": "jobs",
                     "title": "Use the event bus"},
                    run_id="run-1", date="2026-07-01")
        text = self.read("decision", "d-bus")
        self.assertIn("aliases: [Use the event bus]", text)

    def test_alias_omitted_when_title_reslug_matches_id(self):
        self.upsert({"type": "pattern", "id": "outbox", "title": "Outbox"},
                    run_id="run-1", date="2026-07-01")
        self.assertNotIn("aliases:", self.read("pattern", "outbox"))

    def test_alias_union_preserves_user_alias(self):
        rel = kg.note_relpath(self.subfolder, "decision", "d-user")
        path = Path(self.vault, rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\ntype: decision\nid: d-user\ntitle: My decision\n"
            "aliases: [my nickname]\ntags: [spec-loop, decision]\n"
            "runs: [run-1]\ncreated: 2026-07-01\nupdated: 2026-07-01\n---\n"
            "Prose.\n", encoding="utf-8")
        self.upsert({"type": "decision", "id": "d-user",
                     "title": "My decision"},
                    run_id="run-2", date="2026-07-06")
        text = self.read("decision", "d-user")
        self.assertIn("my nickname", text)
        self.assertIn("My decision", text.split("---")[1])

    def test_alias_not_duplicated_across_runs(self):
        node = {"type": "decision", "id": "d-dup", "repo": "jobs",
                "title": "Use the event bus"}
        self.upsert(node, run_id="run-1", date="2026-07-01")
        self.upsert(node, run_id="run-2", date="2026-07-06")
        fm, _body = kg._parse_frontmatter(self.read("decision", "d-dup"))
        self.assertEqual(fm["aliases"], ["Use the event bus"])

    def test_comma_title_alias_roundtrips(self):
        self.upsert({"type": "decision", "id": "d-comma", "repo": "jobs",
                     "title": "Retry, then fail"},
                    run_id="run-1", date="2026-07-01")
        fm, _body = kg._parse_frontmatter(self.read("decision", "d-comma"))
        self.assertEqual(fm["aliases"], ["Retry, then fail"])


# --------------------------------------------------------------------------
# Typed frontmatter — regression pin for Obsidian Bases compatibility
# --------------------------------------------------------------------------

class TestTypedFrontmatter(TempVault):
    def test_dates_unquoted_and_lists_inline(self):
        self.upsert({"type": "decision", "id": "d1", "repo": "jobs",
                     "title": "D1"}, run_id="run-1", date="2026-07-01")
        text = self.read("decision", "d1")
        self.assertIn("created: 2026-07-01\n", text)   # unquoted ISO date
        self.assertIn("updated: 2026-07-01\n", text)
        self.assertIn("tags: [spec-loop, decision, jobs]\n", text)
        self.assertIn("runs: [run-1]\n", text)


# --------------------------------------------------------------------------
# Starter .base — create-once Obsidian Bases table views
# --------------------------------------------------------------------------

class TestBaseFile(TempVault):
    def test_base_created_when_absent(self):
        res = kg.write_base_file(self.vault, self.subfolder)
        self.assertTrue(res["created"])
        text = Path(res["path"]).read_text(encoding="utf-8")
        self.assertIn('file.hasTag("spec-loop")', text)
        for view in ("Runs", "Decisions", "Patterns", "Domain", "Reviews"):
            self.assertIn(f"name: {view}", text)

    def test_base_existing_left_byte_identical(self):
        target = Path(self.vault, self.subfolder, "spec-loop.base")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# user-customized base\n", encoding="utf-8")
        res = kg.write_base_file(self.vault, self.subfolder)
        self.assertFalse(res["created"])
        self.assertEqual(target.read_text(encoding="utf-8"),
                         "# user-customized base\n")

    def test_batch_ensure_base_reports_created(self):
        result = kg._run_batch({
            "vault": self.vault, "subfolder": self.subfolder,
            "run_id": "run-1", "date": "2026-07-01", "repo": "jobs",
            "nodes": [{"type": "system", "id": "jobs", "title": "Jobs"}],
            "ensure_base": True,
        })
        self.assertEqual(result["base"], {"created": True})
        result = kg._run_batch({
            "vault": self.vault, "subfolder": self.subfolder,
            "run_id": "run-1", "date": "2026-07-01", "repo": "jobs",
            "nodes": [], "ensure_base": True,
        })
        self.assertEqual(result["base"], {"created": False})

    def test_base_path_contained(self):
        with self.assertRaises(ValueError):
            kg.write_base_file(self.vault, "../outside")


# --------------------------------------------------------------------------
# Per-repo home index — the System hub's managed kg:index region
# --------------------------------------------------------------------------

class TestRepoIndex(TempVault):
    def seed_and_moc(self):
        return kg._run_batch({
            "vault": self.vault, "subfolder": self.subfolder,
            "run_id": "run-1", "date": "2026-07-06", "repo": "jobs",
            "nodes": [
                {"type": "system", "id": "jobs", "title": "Jobs service",
                 "summary": "The jobs service."},
                {"type": "decision", "id": "d-live", "title": "Live decision"},
                {"type": "decision", "id": "d-old", "title": "Old decision",
                 "status": "superseded"},
                {"type": "pattern", "id": "outbox", "title": "Outbox"},
            ],
            "moc": {"request_title": "Add deposits"},
        })

    def test_hub_index_rebuilt_on_moc_batch(self):
        result = self.seed_and_moc()
        self.assertEqual(result["errors"], [])
        text = self.read("system", "jobs")
        self.assertIn("<!-- kg:index -->", text)
        self.assertIn("## Runs", text)
        self.assertIn("[[run-1|", text)
        self.assertIn("## Active decisions", text)
        self.assertIn("[[d-live|Live decision]]", text)
        self.assertNotIn("[[d-old|", text)          # superseded excluded
        self.assertIn("[[outbox|Outbox]]", text)

    def test_hub_prose_untouched_by_index(self):
        self.seed_and_moc()
        text = self.read("system", "jobs")
        self.assertIn("The jobs service.", text)
        # Prose comes before the managed index region.
        self.assertLess(text.find("The jobs service."),
                        text.find("<!-- kg:index -->"))

    def test_hub_index_scoped_to_repo(self):
        self.seed_and_moc()
        kg._run_batch({
            "vault": self.vault, "subfolder": self.subfolder,
            "run_id": "run-x", "date": "2026-07-07", "repo": "other",
            "nodes": [
                {"type": "system", "id": "other", "title": "Other"},
                {"type": "decision", "id": "d-foreign", "title": "Foreign"},
            ],
            "moc": True,
        })
        text = self.read("system", "jobs")
        self.assertNotIn("[[d-foreign|", text)
        self.assertNotIn("[[run-x|", text)

    def test_moc_batch_retry_with_base_byte_identical(self):
        def snapshot():
            files = {}
            for root, _dirs, names in os.walk(self.vault):
                for name in sorted(names):
                    p = Path(root, name)
                    files[str(p.relative_to(self.vault))] = p.read_bytes()
            return files
        payload = {
            "vault": self.vault, "subfolder": self.subfolder,
            "run_id": "run-1", "date": "2026-07-06", "repo": "jobs",
            "nodes": [
                {"type": "system", "id": "jobs", "title": "Jobs",
                 "summary": "The jobs service."},
                {"type": "decision", "id": "d1", "title": "D1",
                 "links": ["jobs"]},
            ],
            "moc": {"request_title": "Add deposits"},
            "ensure_base": True,
        }
        kg._run_batch(payload)
        first = snapshot()
        kg._run_batch(payload)
        self.assertEqual(first, snapshot())


# --------------------------------------------------------------------------
# Run-DAG canvas — JSON Canvas 1.0 projection of the run's slices/waves
# --------------------------------------------------------------------------

class TestCanvas(TempVault):
    DAG = {
        "slices": [
            {"id": "a", "goal": "Seed the schema", "deps": [],
             "risk_tier": 1, "status": "complete"},
            {"id": "b", "goal": "API layer", "deps": ["a"],
             "risk_tier": 2, "status": "complete"},
            {"id": "c", "goal": "Worker", "deps": ["a"],
             "risk_tier": 3, "status": "complete"},
            {"id": "d", "goal": "Wire together", "deps": ["b", "c"],
             "risk_tier": 2, "status": "complete"},
        ]
    }

    def write_dag(self, dag=None):
        path = Path(self.vault, "dag.json")
        path.write_text(json.dumps(dag or self.DAG), encoding="utf-8")
        return str(path)

    def canvas_path(self):
        return Path(self.vault, self.subfolder, "Runs", "run-1.canvas")

    def batch(self, **overrides):
        payload = {
            "vault": self.vault, "subfolder": self.subfolder,
            "run_id": "run-1", "date": "2026-07-06", "repo": "jobs",
            "nodes": [{"type": "system", "id": "jobs", "title": "Jobs"}],
            "moc": {"request_title": "Add deposits"},
            "canvas": {"dag_file": self.write_dag()},
        }
        payload.update(overrides)
        return kg._run_batch(payload)

    def test_layer_slices_longest_path(self):
        waves = kg.layer_slices(self.DAG["slices"])
        self.assertEqual(waves, {"a": 0, "b": 1, "c": 1, "d": 2})

    def test_layer_slices_excludes_split_parents(self):
        slices = [
            {"id": "p", "deps": [], "status": "split"},
            {"id": "p1", "deps": [], "parent": "p", "status": "complete"},
            {"id": "p2", "deps": ["p1"], "parent": "p", "status": "complete"},
            # A dep on the split parent is dropped defensively.
            {"id": "q", "deps": ["p"], "status": "complete"},
        ]
        waves = kg.layer_slices(slices)
        self.assertNotIn("p", waves)
        self.assertEqual(waves["p1"], 0)
        self.assertEqual(waves["p2"], 1)
        self.assertEqual(waves["q"], 0)  # its only dep was the split parent

    def test_canvas_written_and_spec_valid(self):
        result = self.batch()
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["canvas"], {"created": True})
        data = json.loads(self.canvas_path().read_text(encoding="utf-8"))
        self.assertIn("nodes", data)
        self.assertIn("edges", data)
        text_nodes = [n for n in data["nodes"] if n["type"] == "text"]
        self.assertEqual(len(text_nodes), 4)
        for node in data["nodes"]:
            for key in ("id", "type", "x", "y", "width", "height"):
                self.assertIn(key, node)
        for edge in data["edges"]:
            for key in ("id", "fromNode", "toNode"):
                self.assertIn(key, edge)
        # Edges mirror the dag deps.
        pairs = {(e["fromNode"], e["toNode"]) for e in data["edges"]}
        self.assertEqual(pairs, {("s-a", "s-b"), ("s-a", "s-c"),
                                 ("s-b", "s-d"), ("s-c", "s-d")})
        # Risk-tier colors: 1 green(4), 2 yellow(3), 3 red(1).
        colors = {n["id"]: n["color"] for n in text_nodes}
        self.assertEqual(colors["s-a"], "4")
        self.assertEqual(colors["s-b"], "3")
        self.assertEqual(colors["s-c"], "1")
        # One group per wave.
        groups = [n for n in data["nodes"] if n["type"] == "group"]
        self.assertEqual({g["label"] for g in groups},
                         {"Wave 0", "Wave 1", "Wave 2"})

    def test_canvas_deterministic(self):
        self.batch()
        first = self.canvas_path().read_bytes()
        self.canvas_path().unlink()
        self.batch()
        self.assertEqual(first, self.canvas_path().read_bytes())

    def test_canvas_create_once(self):
        self.canvas_path().parent.mkdir(parents=True, exist_ok=True)
        self.canvas_path().write_text('{"nodes": [], "edges": []}',
                                      encoding="utf-8")
        result = self.batch()
        self.assertEqual(result["canvas"], {"created": False})
        self.assertEqual(self.canvas_path().read_text(encoding="utf-8"),
                         '{"nodes": [], "edges": []}')

    def test_malformed_dag_collected_not_raised(self):
        bad = Path(self.vault, "bad-dag.json")
        bad.write_text("not json", encoding="utf-8")
        result = self.batch(canvas={"dag_file": str(bad)})
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["node"], "canvas")
        self.assertEqual(result["upserted"], 1)  # batch itself still succeeded

    def test_moc_links_canvas(self):
        self.batch()
        text = self.read("run", "run-1")
        self.assertIn("[[run-1.canvas]]", text)

    def test_canvas_goal_redacted(self):
        dag = {"slices": [{"id": "a", "deps": [], "risk_tier": 1,
                           "status": "complete",
                           "goal": "Rotate password=hunter2secret now"}]}
        self.batch(canvas={"dag_file": self.write_dag(dag)})
        text = self.canvas_path().read_text(encoding="utf-8")
        self.assertNotIn("hunter2secret", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
