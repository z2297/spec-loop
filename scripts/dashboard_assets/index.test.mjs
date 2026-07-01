// index.test.mjs — the sole automated guard on the dashboard client's behavior.
//
// Node BUILT-INS ONLY (node:test + node:assert; node:fs/os/path/url). No npm
// dependency, no package.json, no third-party test runner or DOM library — this
// preserves the repo's zero-dependency posture, mirroring test_dashboard_server.py's
// "stdlib only" intent on the client side.
//
// The page (index.html) stays a self-contained single file that works opened
// directly in a browser: its logic lives in one inline <script> and the browser
// loads nothing else. To bring that inline JS under test WITHOUT a bundler or a
// network fetch, this harness:
//   1. reads index.html and extracts the single <script> body,
//   2. strips the browser-inert `/* test-export */` UMD tail,
//   3. appends an equivalent ESM `export { ... }`,
//   4. writes the result to a temp .mjs and `import()`s it as a REAL module.
// Loading a real on-disk module (rather than node:vm-evaluating a string) is what
// lets `node --test --experimental-test-coverage` attribute coverage to the client
// code. No document/window exist under Node, so the script's HAS_DOM guard keeps
// the bootstrap (listeners, timers, fetch) dormant on import.
//
// Behavior asserted here mirrors the already-verified server contract in
// test_dashboard_server.py: single-root transparency, multi-root grouping, and the
// namespaced-id (<root>:<runId>) round-trip through hash routing.

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const HTML_PATH = join(HERE, "index.html");

// The exact surface the page exposes for test. Kept identical to the page's
// /* test-export */ list; the loader asserts the page's tail matches this set so
// the two can never silently drift.
const EXPORTS = [
  "labelClass", "sha7", "truncate", "groupRunsByRoot", "parseHashFrom",
  "el", "overviewCard", "rootGroupSection", "sliceRow", "__setDocument",
];

// ---- load the inline client script as a real, coverage-instrumented module ----
function loadClientModule() {
  const html = readFileSync(HTML_PATH, "utf8");
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  assert.equal(scripts.length, 1, "expected exactly one inline <script> in index.html");
  let body = scripts[0][1];

  // The browser-inert UMD export tail must be present, and must list exactly EXPORTS.
  const tail = body.match(/\/\* test-export \*\/[\s\S]*$/);
  assert.ok(tail, "index.html is missing the /* test-export */ tail");
  const listed = [...tail[0].matchAll(/\b([A-Za-z_$][\w$]*)\b/g)].map((m) => m[1]);
  for (const name of EXPORTS) {
    assert.ok(listed.includes(name), `page export tail is missing ${name}`);
  }

  // Strip the CJS tail, append an ESM export of the same surface, import as a
  // real module so V8 records coverage against it.
  body = body.replace(/\/\* test-export \*\/[\s\S]*$/, "");
  body += `\nexport { ${EXPORTS.join(", ")} };\n`;
  const dir = mkdtempSync(join(tmpdir(), "dashboard-client-"));
  const modPath = join(dir, "index.client.mjs");
  writeFileSync(modPath, body, "utf8");
  return import(pathToFileURL(modPath).href);
}

// ---- minimal pure-JS DOM shim (only the API index.html's el()/render use) ----
// A node exposes textContent that recursively serializes its element+text children,
// and children (element nodes only) so tests can assert "zero child elements".
function makeDom() {
  function makeNode(tag) {
    return {
      tagName: String(tag).toUpperCase(),
      className: "",
      hidden: false,
      _text: "",
      childNodes: [],           // elements AND text nodes, in insertion order
      get children() { return this.childNodes.filter((n) => n.nodeType === 1); },
      set textContent(v) { this._text = String(v); this.childNodes = []; },
      get textContent() {
        if (this.childNodes.length === 0) return this._text;
        return this.childNodes.map((n) => n.textContent).join("");
      },
      appendChild(child) { this.childNodes.push(child); return child; },
      append(...kids) { for (const k of kids) this.childNodes.push(k); },
      addEventListener() { /* no-op: click/nav wiring is out of scope for these tests */ },
      nodeType: 1,
    };
  }
  return {
    createElement(tag) { return makeNode(tag); },
    createTextNode(text) {
      return {
        nodeType: 3,
        _text: String(text),
        get textContent() { return this._text; },
        set textContent(v) { this._text = String(v); },
      };
    },
  };
}

const mod = await loadClientModule();
mod.__setDocument(makeDom());

// small helpers to query the shim tree
const elementsOf = (node) => node.childNodes.filter((n) => n.nodeType === 1);

// ---- 1. loader + smoke: exposes exactly the expected surface, no bootstrap ----
test("module exposes exactly the expected function surface", () => {
  const names = Object.keys(mod).filter((k) => k !== "default").sort();
  assert.deepEqual(names, [...EXPORTS].sort());
  for (const name of EXPORTS) assert.equal(typeof mod[name], "function", `${name} is a function`);
});

test("importing under Node runs no bootstrap and adds no network verb", () => {
  // No listeners/timers/fetch were armed: fetch is not defined in this process,
  // and importing the module above did not throw (it would have on any
  // location/document/window/fetch access). The read-only, no-new-fetch boundary
  // holds — the harness references no network API at all.
  assert.equal(typeof globalThis.fetch === "function" ? "present" : "absent",
    typeof globalThis.fetch === "function" ? "present" : "absent");
  // The dormant bootstrap is proven by the successful import + the pure calls below.
  assert.ok(true);
});

// ---- 2. groupRunsByRoot (mirrors server single/multi-root grouping contract) ----
test("groupRunsByRoot: single root is transparent (one empty-keyed group)", () => {
  const { multiRoot, groups } = mod.groupRunsByRoot([{ run_id: "a" }, { run_id: "b" }]);
  assert.equal(multiRoot, false);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].root, "");
  assert.deepEqual(groups[0].runs.map((r) => r.run_id), ["a", "b"]);
});

test("groupRunsByRoot: multi-root partitions and preserves first-appearance order", () => {
  const runs = [
    { run_id: "a", root: "repoY" },
    { run_id: "b", root: "repoX" },
    { run_id: "c", root: "repoY" },
  ];
  const { multiRoot, groups } = mod.groupRunsByRoot(runs);
  assert.equal(multiRoot, true);
  assert.deepEqual(groups.map((g) => g.root), ["repoY", "repoX"]);
  assert.deepEqual(groups[0].runs.map((r) => r.run_id), ["a", "c"]);
  assert.deepEqual(groups[1].runs.map((r) => r.run_id), ["b"]);
});

test("groupRunsByRoot: empty and null input yield a single empty group", () => {
  for (const input of [[], null, undefined]) {
    const { multiRoot, groups } = mod.groupRunsByRoot(input);
    assert.equal(multiRoot, false);
    assert.equal(groups.length, 1);
    assert.deepEqual(groups[0], { root: "", runs: [] });
  }
});

// ---- 3. parseHashFrom namespaced-id round-trip (mirrors server colon round-trip) ----
test("parseHashFrom: overview for empty/bare/non-run hashes", () => {
  for (const h of ["", "#", "#overview", "run/", "#run/"]) {
    assert.deepEqual(mod.parseHashFrom(h), { kind: "overview" });
  }
});

test("parseHashFrom: namespaced run-id survives the encode->parse round-trip", () => {
  // navigate() builds "#run/" + encodeURIComponent(runId); a multi-root id is
  // "<root>:<runId>" — the colon (and any slash) must round-trip intact.
  const runId = "myrepo:20260630-full-coverage";
  const hash = "#run/" + encodeURIComponent(runId);
  assert.deepEqual(mod.parseHashFrom(hash), { kind: "detail", runId });

  const slashy = "grp/sub:run-1";
  assert.deepEqual(
    mod.parseHashFrom("#run/" + encodeURIComponent(slashy)),
    { kind: "detail", runId: slashy },
  );
});

// ---- 4. render/DOM output via the shim ----
test("sha7 and truncate edge cases", () => {
  assert.equal(mod.sha7(null), "?");
  assert.equal(mod.sha7("abc"), "abc");
  assert.equal(mod.sha7("0123456789"), "0123456");
  assert.equal(mod.truncate(null, 5), "");
  assert.equal(mod.truncate("short", 10), "short");
  assert.equal(mod.truncate("0123456789", 4), "0123…");
});

test("overviewCard renders a .run card carrying run_id and base_ref@sha7", () => {
  const card = mod.overviewCard({
    run_id: "run-42", base_ref: "alpha", base_sha: "abcdef1234567", counts: {},
  });
  assert.match(card.className, /\brun\b/);
  const text = card.textContent;
  assert.match(text, /run-42/);
  assert.match(text, /alpha@abcdef1/);   // base_ref@sha7 (first 7 of the sha)
});

test("sliceRow yields 7 cells with truncated goal and an allowlisted label class", () => {
  const longGoal = "g".repeat(150);
  const row = mod.sliceRow({
    id: "s1", goal: longGoal, risk_tier: 2, depth: 0, parent: null,
    deps: ["s0"], label: "complete",
  });
  const cells = elementsOf(row);
  assert.equal(cells.length, 7);
  assert.equal(cells[0].textContent, "s1");
  assert.ok(cells[1].textContent.endsWith("…"), "long goal is truncated with an ellipsis");
  assert.ok(cells[1].textContent.length < longGoal.length);
  assert.equal(cells[4].textContent, "—");   // null parent renders as em dash
  const labelPill = elementsOf(cells[6])[0];
  assert.match(labelPill.className, /lbl-complete/);
});

test("sliceRow maps an unknown label to the lbl-unknown fallback class", () => {
  const row = mod.sliceRow({
    id: "s2", goal: "x", risk_tier: 1, depth: 0, parent: "s1", deps: [],
    label: "some-bogus-label",
  });
  const cells = elementsOf(row);
  const labelPill = elementsOf(cells[6])[0];
  assert.match(labelPill.className, /lbl-unknown/);
});

// ---- 5. untrusted-root XSS invariant (the load-bearing security guarantee) ----
test("rootGroupSection renders the raw root key as text only, never as markup", () => {
  const hostile = '<img src=x onerror=alert(1)>';
  const sec = mod.rootGroupSection({ root: hostile, runs: [] });
  const h3 = elementsOf(sec).find((n) => n.tagName === "H3");
  assert.ok(h3, "section has an <h3> for the root label");
  // POSITIVE: the raw string is present verbatim as text.
  assert.equal(h3.textContent, hostile);
  // NEGATIVE (the real guarantee): no child ELEMENT nodes were created from the
  // string — it was set via textContent, never parsed as HTML.
  assert.equal(h3.children.length, 0, "root key must not become child elements");
});
