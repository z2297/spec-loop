---
description: "Start a local read-only web dashboard server (modern dark-theme single-page UI over the run artifacts under docs/spec-loop/<run-id>/) by launching scripts/dashboard_server.py; mutates no run state and triggers no slice work"
argument-hint: "[--port N] [--root PATH]"
allowed-tools: ["Bash"]
---

# Spec-Loop Dashboard — serve the read-only web UI

Launch the local, **read-only** web dashboard: a self-contained dark-theme single-page UI that
renders a `/spec-loop` run from the durable artifacts under `docs/spec-loop/<run-id>/`, with an
all-runs overview, a single-run drill-down (DAG/waves, slice table, status rollup, open
escalations, recent decisions), and near-real-time auto-refresh.

This command **mutates no run state** and **triggers no slice work** — it only starts
`scripts/dashboard_server.py`, a server that binds `127.0.0.1` only, answers `GET`/`HEAD`
exclusively (every other verb is `405`), shells out to nothing, and writes no files. Starting a
long-lived local process *is* a side effect; the read-only guarantee is about your **run state**,
which the dashboard never changes. The `Bash` tool is permitted **only** to launch the server (and,
if needed, to stop it with `Ctrl-C`); never use it to write, move, or delete anything. There is no
`Write`, `Edit`, `Task`, or `AskUserQuestion` capability here, and that is the security boundary —
keep it intact.

## Steps

1. **Pick a port (optional).** The server defaults to `8787`. If that port is busy, pass a
   different one with `--port N`. Use any ephemeral/free port; do not assume `8787` is available.

2. **Pick a root (optional).** By default the server scans `docs/spec-loop/` under the current
   working directory. To view a different repo's runs, pass `--root PATH` pointing at that repo
   root (the directory containing `docs/spec-loop/`). The server confines all reads to that root.

3. **Launch the server (read-only).** Run, via `Bash`:

   ```
   python3 scripts/dashboard_server.py [--port N] [--root PATH]
   ```

   It is pure Python standard library — no install, no node/npm, no build step. It prints the
   bound URL, e.g. `open http://127.0.0.1:<port>/`.

4. **Open the printed URL.** Visit `http://127.0.0.1:<port>/` in a browser. The page loads the
   dark-theme UI, lists every run in this repo, and auto-refreshes (~2.5s) with a visible
   "updated Ns ago" freshness indicator. Click a run to drill into its DAG, waves, slice table,
   rollup, open escalations, and recent decisions. A run whose `dag.json` is momentarily
   half-written renders as a transient "state momentarily unreadable" card, never an error.

5. **Stop the server.** Press `Ctrl-C` in the terminal running the server when finished.

## Notes
- **Read-only contract.** The page can only issue `GET` requests against the server's `/api/runs`
  and `/api/runs/<id>` JSON endpoints; it has **no** control that triggers, resumes, cancels, or
  otherwise mutates a run. The server enforces this server-side (`GET`/`HEAD` only, `127.0.0.1`
  bind, Host-header allowlist, path-traversal-safe run resolution) — `allowed-tools` is limited to
  `Bash` (to launch it) and nothing that could write.
- **Distinct from `/spec-loop:dashboard`.** `/spec-loop:dashboard` prints a one-shot
  **terminal-markdown** snapshot of a run and starts no server. `dashboard-serve` is the
  **live web** dashboard — the richer auto-refreshing HTML view that `dashboard.md` reserved as a
  deliberate future follow-on. Use whichever fits: terminal for a quick glance, web for a
  near-real-time, navigable view.
- **This repo's runs only.** The server discovers runs by globbing `docs/spec-loop/*/dag.json`
  under `--root`; it does not perform any machine-wide or cross-repo scan.
- **Single source of truth.** Waves and per-slice readiness labels are **derived** (never stored),
  using the exact rules of `/spec-loop:dashboard`; `dag.json` is the only authority for run state.
