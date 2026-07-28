---
description: "Start-or-reuse the machine-wide read-only web dashboard (a modern dark-theme single-page UI over the run artifacts under docs/spec-loop/<run-id>/, aggregated across every repo you have launched from) via the plugin-bundled dashboard_launcher.py: Docker-preferred, python-fallback; mutates no run state and triggers no slice work. Pass --stop to tear the singleton down"
argument-hint: "[--stop]"
allowed-tools: ["Bash"]
---

# Spec-Loop Dashboard — serve the read-only web UI

Launch the local, **read-only** web dashboard: a self-contained dark-theme single-page UI
over the durable artifacts under `docs/spec-loop/<run-id>/`, with an all-runs overview, a
single-run drill-down (DAG/waves, slice table, status rollup, open escalations, recent
decisions), and near-real-time auto-refresh. It is a **machine-wide singleton** that
aggregates the runs of every repo you launch it from into one view — one container, one URL,
all your sessions.

This command mutates no run state and triggers no slice work. `Bash` is the only capability,
and it is used to shell out to `docker` — building the image on first run, running the
detached container, and stopping it via `--stop`. Starting a container (or a foreground
process) *is* a side effect; the read-only guarantee is about your **run state**, which the
dashboard physically cannot change: artifacts are bind-mounted `:ro`, the container drops
all capabilities and runs non-root, and the Docker socket is not mounted. There is no
`Write`, `Edit`, `Task`, or `AskUserQuestion` here — that is the security boundary, so keep
the frontmatter exact.

## Steps

1. **Start (or reuse) the dashboard.** Run, via `Bash`, **from the repo whose runs you want
   included** — your current working directory selects the served repo, while the launcher
   itself is bundled in the plugin and addressed by its absolute path:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/dashboard_launcher.py"
   ```

   There is no `--port` flag; the singleton always publishes the fixed port `8787` on
   loopback. The launcher then decides:

   - **Docker daemon available → Docker path.** It launches (or reuses) one fixed
     machine-wide container named `spec-loop-dashboard`, prints the loopback URL, and
     **exits** — it does not hold your shell. The container is detached and keeps serving
     after the command returns.
   - **Docker absent or daemon down → Python fallback.** It prints a one-line message on
     stderr saying it fell back and why (e.g. `docker unavailable (docker not installed);
     falling back to a local foreground server`), then runs the bundled
     `dashboard_server.py --root <cwd>` **in the foreground**. This path is fully functional
     — that process *is* the listener — and stays attached until `Ctrl-C`.

   On the very first Docker invocation the launcher builds `spec-loop-dashboard:local` from
   the bundled `Dockerfile`, which can take tens of seconds. Later launches reuse the image.

2. **Open the printed URL** — `http://127.0.0.1:8787/`. The page lists runs from every
   registered repo and auto-refreshes with a visible freshness indicator. Click a run to
   drill into its DAG, waves, slice table, rollup, open escalations, and recent decisions. A
   run whose `dag.json` is momentarily half-written renders as a transient "state momentarily
   unreadable" card, never an error.

3. **Add more repos to the view — just run the launcher there too.** A launch from a second
   repo registers it and recreates the shared singleton with the union of per-root `:ro`
   mounts, so one dashboard serves both. Docker has no in-place mount addition, so this
   stop-and-recreate is how cross-repo aggregation works — it briefly blips any open
   browsers while the container cycles, and a refresh reconnects them to the same URL.

4. **Stop the dashboard.**
   - **Docker path:** `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/dashboard_launcher.py" --stop`.
     This is scoped to the singleton name only (`docker stop spec-loop-dashboard` then
     `docker rm spec-loop-dashboard`) — it never touches another container and never uses an
     unscoped `rm -f`.
   - **Python-fallback path:** press `Ctrl-C` in the foreground terminal.

## Notes

- **Idempotent singleton.** Re-running the launcher with the current set of repos reuses the
  running container: it reprints the URL and exits without starting a second one. Docker's
  `--name` uniqueness is the authoritative lock — if two launches race, the loser treats the
  name-in-use error as "already up," reprints the URL, and exits `0`, never duplicating and
  never falling back to Python just because of the race.
- **Lifecycle differs by path.** Docker returns immediately and keeps serving in the
  background until `--stop`; the Python fallback stays in the foreground because that process
  is the server. Know which one you got from the printed message.
- **Stale roots are pruned at launch.** A repo whose path moved or was deleted, or that has
  not been launched from in roughly the last 6 hours, drops out of the aggregated view. There
  is no background reaper — pruning happens only when you run the launcher.
- **Distinct from `/spec-loop:dashboard`,** which prints a one-shot terminal-markdown
  snapshot of a single run and starts no server. Waves and readiness labels here are derived
  by the same rules, and `dag.json` remains the only authority for run state.
