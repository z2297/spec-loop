---
schema_version: 1
review_id: local-b24b3d7-e590fc8
target:
  provider: local
  pr_id: ""
  base_sha: b24b3d703a803093736056699241a1361208af97
  head_sha: e590fc80dc14182fe8a5cdc3e7648cf0cebf48d4
requirements_source: docs/pr-review/local-b24b3d7-e590fc8/requirements.md
verdict: APPROVE_WITH_COMMENTS
severity_counts: { P0: 0, P1: 4, P2: 13 }
generated: 2026-06-30T01:06:22Z
---

# Peer-review report — `main..alpha` (`b24b3d7..e590fc8`)

Local ref-range review of the **alpha** channel's net-new peer-review feature work: the
read-only PR/ref-range resolver (`scripts/pr_resolver.py`), the five `peer-review-*`
reviewer agents, the `peer-review-council` skill, the `/spec-loop:peer-review` command,
the read-only web dashboard (`scripts/dashboard_server.py` + `index.html`), the
`validate_marketplace.py` CI-gate hardening, and three new test suites. 31 commits, 26
files, +5104/-11. Requirements judged: *"run claude in a loop using spec files and review
against those spec files to ensure alignment of work."*

**Verdict: APPROVE_WITH_COMMENTS.** No P0, no `SAFETY` blocker, no security hole, no data
loss, no broken public contract. Every stated and implicit requirement is delivered. The
changeset is unusually well-hardened. The four P1s are one real (narrow-trigger) runtime
defect plus three test-coverage gaps on existing-and-correct guards — worth closing before
promoting alpha → beta, but none is a blocking defect on the merged code.

## Requirement traceability

(Sourced verbatim from the `conformance` reviewer's matrix.)

| Requirement | Status | Evidence (file:line) | Finding ref |
|-------------|--------|----------------------|-------------|
| Review a real diff against supplied business requirements to ensure alignment of work | covered | `plugins/spec-loop/commands/peer-review.md:1-144`; council convened `:103-120`; matrix mandate `skills/peer-review-council/SKILL.md:131-134` | — |
| Provider-agnostic, read-only PR/ref-range resolver | covered | `scripts/pr_resolver.py:267-365`; CLI `:459-489`; 4 providers `:67-90` | — |
| Five `peer-review-*` reviewer agents | covered | `plugins/spec-loop/agents/peer-review-{conformance,correctness,risk,design,tests}.md` | — |
| `peer-review-council` skill (convene + aggregate + report schema) | covered | `SKILL.md:78-110`, `:136-193`, `:195-311` | — |
| `/spec-loop:peer-review` command driving the loop | covered | `plugins/spec-loop/commands/peer-review.md:48-144` | — |
| Read-only web dashboard + supporting tests | covered | `scripts/dashboard_server.py:342-374`, `:476-501`; `scripts/dashboard_assets/index.html:1`; `scripts/test_dashboard_server.py` | — |
| Loop is genuinely READ-ONLY (no edits/merges/posts/provider mutations) | covered | `peer-review.md:23-46`; resolver READ verbs only `pr_resolver.py:38-42,170-188`; CI gate enforces it `validate_marketplace.py:197-216` | #P2-1 |
| Inputs treated as untrusted (no shell injection, no path traversal) | covered | `pr_resolver.py:101-109`, `:355-359,391-392,410`; `dashboard_server.py:67-89`, `:403-412` | — |
| Published artifact conforms to the pinned council schema | covered | `SKILL.md:210-311`; command writes conforming report `peer-review.md:125-139` | — |
| Loop uses spec files / supplied requirements as the review basis | covered | requirements persisted verbatim then reviewed `peer-review.md:95-101`; matrix sourced from spec `SKILL.md:131-134,233-244` | — |

All requirements **covered**. No requirement is `violated` or `unclear`.

## Merged findings

### P0
_None._

### P1

- **#P1-1** — source: review-pr:silent-failure-hunter — `scripts/pr_resolver.py:163` (`_run`) — `subprocess.run(..., text=True)` decodes stdout with the default `errors='strict'`, so a `git diff` whose body contains non-UTF-8 text (a file git treats as text but that isn't valid UTF-8 — e.g. Latin-1 source) raises an **uncaught `UnicodeDecodeError`**. It is neither `FileNotFoundError` (caught in `_run`) nor `ResolverError` (caught in `main()`), so the process dies with a raw traceback and **exit 1**, violating the documented fail-closed contract (`error: <msg>` + exit 2, "never half-resolves"). Trigger is narrow — git emits "Binary files differ" for NUL-containing files — but real and reachable. — remedy: pass `errors="replace"` to `subprocess.run` in `_run` (or capture bytes and decode leniently at the boundary). *Not independently caught by the correctness/risk council lanes.*
- **#P1-2** — source: tests (corroborated by review-pr:pr-test-analyzer) — `scripts/dashboard_server.py:493` — the spec-named guarantee "binds 127.0.0.1 only" has **no direct test**; a regression to `""`/`0.0.0.0` (exposing the read-only dashboard, including artifact contents, to the LAN) would pass the entire suite. The Host-header allowlist defense-in-depth *is* well tested, but that is a different guarantee. — remedy: assert `build_server(...).server_address[0] == "127.0.0.1"` (one line, pins the most security-load-bearing line in the file).
- **#P1-3** — source: review-pr:pr-test-analyzer — `scripts/validate_marketplace.py:136-150` (`validate_source_object`) — the entire method is **untested**, including the 40-hex `SHA` pin (`:134`) that is a supply-chain integrity control. A regression accepting an unknown `source.source` kind, dropping a required key, or weakening/​shortening the SHA pin would be silent. (The code itself was reviewed sound by the risk and correctness lanes.) — remedy: add per-kind valid + missing-required-key cases, an invalid kind, an empty `ref`, and a malformed/short/non-hex `sha`.
- **#P1-4** — source: review-pr:pr-test-analyzer — `scripts/validate_marketplace.py:107-109` — the `".." in source` **path-traversal guard** has no test (the parallel dashboard guard *is* tested). Removal/weakening would let a marketplace entry resolve a plugin dir outside the repo root, unnoticed. — remedy: one test — a `source` of `"../evil"` must produce the "must not contain '..'" error and fail validation.

### P2

- **#P2-1** — source: conformance — `scripts/pr_resolver.py:398-432` (`resolve_diff`) — materializes the diff via `git fetch` into the user's `--repo-dir`, writing objects/refs into the local clone. Requirement met as documented (`pr_resolver.py:29-31` states "it fetches the refs it needs into it"); the "read-only" framing is scoped to the PR/provider, not the local clone. — remedy: none for conformance; keep the explicit "fetches the refs it needs" wording so the contract stays honest.
- **#P2-2** — source: review-pr:silent-failure-hunter — `scripts/pr_resolver.py:333` (`resolve_local`) — a local range whose base/head resolve to the **same** SHA emits an empty diff with exit 0 and no signal distinguishing "mistyped range" from "legitimately identical commits," so a peer-review run over a mistyped range reviews nothing yet reports success. — remedy: when `--diff` is requested and `base_sha == head_sha`, print a `note:` to stderr.
- **#P2-3** — source: review-pr:silent-failure-hunter — `scripts/dashboard_server.py:122` (`_scan_one_run`) — `dag.json` is read via unbounded `read_text()`, **bypassing the `MAX_FILE_BYTES` cap** every other artifact uses (contradicts the "bounded bytes" guardrail; per-request memory amplification, bounded blast radius since localhost-only/read-only), and a UTF-8-undecodable `dag.json` is folded into the same `"unreadable"` bucket as a half-written one. — remedy: read `dag.json` through `_read_text_capped`; optionally distinguish a persistent `"corrupt"` state from a transient `"unreadable"` one.
- **#P2-4** — source: review-pr:silent-failure-hunter — `scripts/dashboard_server.py:92` (`_read_text_capped`) — a mid-write/oversized `escalations.md` truncated at `MAX_FILE_BYTES` is parsed as authoritative, so an OPEN escalation past the cap silently vanishes and `awaiting-human` can under-report a slice genuinely waiting on a human. — remedy: detect an at-cap read (`read(MAX_FILE_BYTES)` returning exactly the cap) and surface a degraded signal rather than parsing a truncated body.
- **#P2-5** — source: review-pr:silent-failure-hunter — `scripts/pr_resolver.py:401` (`_materialize_commits`) — the per-fetch `except ResolverError: pass` is correct by design, but the final unreachable-commit error discards the swallowed fetch reasons (auth vs offline vs server-refuses-bare-SHA), so the actionable message lacks the cause. — remedy: accumulate the swallowed fetch error strings and append the last/deduped set to the raised `ResolverError`.
- **#P2-6** — source: design — `scripts/dashboard_server.py:177` and `plugins/spec-loop/commands/dashboard.md:57-99` — wave/label derivation is mirrored as Python (`_derive_waves`/`_derive_label`/`scan_runs`) **and** as prose Steps 1-8; both files claim a "single source of truth" yet the *logic* must be hand-synchronized across two languages (only `dag.json` data is truly single-sourced). — remedy: have `dashboard.md` normatively cite `scan_runs` as the executable spec instead of restating the rules.
- **#P2-7** — source: design — `plugins/spec-loop/agents/peer-review-{conformance,correctness,risk,design,tests}.md` — the per-member output block is byte-identical across all five agents (intended for standalone self-containment; `SKILL.md` correctly names the agents as the source) but must be kept in lockstep by hand. — remedy: none structural; keep the five blocks identical on any future schema edit.
- **#P2-8** — source: design — `scripts/pr_resolver.py:249` (`_normalized_remote`) — a very thin kwargs→dict wrapper adding one indirection layer (earns its keep on call-site readability in the three remote resolvers). — remedy: optional; keep.
- **#P2-9** — source: correctness — `scripts/validate_marketplace.py:240` (`_frontmatter_value_error`) — a value like `"x": y"` (leading-and-trailing same quote, but not a single quoted scalar) slips the colon-space check; explicitly documented out-of-scope and deferred to CI's authoritative `claude plugin validate`. — remedy: none required; noted for completeness.
- **#P2-10** — source: risk — `scripts/dashboard_server.py:483` — defense-in-depth: `--root` is operator-supplied; reads are `realpath`-confined under it, but pointing `--root` at a tree containing sensitive/symlinked `docs/spec-loop/*/` artifacts would serve them to any localhost process (low risk — localhost-only, operator-chosen, read-only). — remedy: document that `--root` should be a trusted repo root; optionally reject run dirs that are symlinks.
- **#P2-11** — source: tests (corroborated by review-pr:pr-test-analyzer) — `scripts/test_dashboard_server.py` — risky-path test edges: HEAD exercised only on the 200 path (not the 404/421 `write_body=False` branch); the 405 test asserts status but not an inert body / no data leak; `test_run_id_traversal_returns_404` passes at the allowlist step *before* `resolve_within` runs (containment is proven separately in `ContainmentTests`, so coverage holds overall, but the test name overstates what it proves); `PATCH`/`OPTIONS` are not in the rejected-verb loop. — remedy: add HEAD-on-404, a 405-body assertion, and `PATCH`/`OPTIONS` to the loop.
- **#P2-12** — source: review-pr:pr-test-analyzer — `scripts/validate_marketplace.py:58-173` and `scripts/pr_resolver.py:145-202` — additional generic branch-coverage gaps: validator duplicate-name / name-version-mismatch / `pluginRoot`-prefixing / marketplace-shape errors; resolver `_http_get` `HTTPError` branch (only `URLError` is tested) and a `method="GET"` assertion; Azure path-parser internal rejection branches; static-asset `Content-Type` + `X-Content-Type-Options: nosniff` headers. — remedy: add the focused negative/branch tests as enumerated.
- **#P2-13** — source: review-pr:code-reviewer — `scripts/dashboard_server.py:285-290` (`_parse_escalation_header`/`_header_state`) — escalation parsing matches the literal `(status: OPEN)` with exactly one space and truncates the title at the first `(status:`; a hand-edited `escalations.md` with different spacing reads as unknown state, and a title containing that substring is clipped. Format is producer-controlled (escalation-gate), so a robustness note, not a live bug. — remedy: tolerate spacing variance, or anchor the marker.

## Dedup / corroboration note

- **#P1-2** merges the `tests` council finding (`dashboard_server.py:493`, rated defense-in-depth) with `review-pr:pr-test-analyzer`'s C1 at the same line; the council finding is kept and the toolkit lane is cited as corroboration. Two independent lanes flagging a literal spec guarantee with zero direct assertion is why the merged severity is raised to P1 (above the council lane's standalone P2).
- **#P2-11** likewise merges the `tests` council edge-case notes with `pr-test-analyzer`'s "Test Quality Issues"; council finding kept, toolkit cited.
- **Severity normalization caveat (transparent):** `review-pr:silent-failure-hunter` rated **#P1-1** *CRITICAL* and `pr-test-analyzer` rated **#P1-3/#P1-4** *Critical (8)* on their own coverage/robustness scales. The council mapping (review-pr Critical → P0) was **not applied literally** here: on the unified scale a P0 means a *blocking defect / SAFETY hole*, whereas #P1-1 is a narrow-trigger crash on otherwise-sound code and #P1-3/#P1-4 are missing tests for *existing, correct* guards (the guards themselves passed the risk and correctness lanes). They are placed at P1 — "important, fix before promotion" — rather than P0. This is the "normalize by severity rank / lane context" latitude the council schema grants, not a literal-label match.
- The five council lanes have near-zero mutual overlap by construction (their non-overlap boundaries held); the only council↔council adjacency was the local-`git fetch` observation, which conformance raised and explicitly deferred to risk's lane (#P2-1).
- **Redaction:** no secret, credential, token, or PII appeared in the diff, the requirements, or any reviewer's evidence (the `risk` lane explicitly verified the Bitbucket bearer token never reaches argv or error text). No value required `[REDACTED]`.
