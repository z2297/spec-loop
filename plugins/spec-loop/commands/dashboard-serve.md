---
description: "Start-or-reuse the machine-wide read-only web dashboard (a modern dark-theme single-page UI over the run artifacts under docs/spec-loop/<run-id>/, aggregated across every repo you have launched from) via scripts/dashboard_launcher.py: Docker-preferred, python-fallback; mutates no run state and triggers no slice work. Pass --stop to tear the singleton down"
argument-hint: "[--stop]"
allowed-tools: ["Bash"]
---

# Spec-Loop Dashboard — serve the read-only web UI

Launch the local, **read-only** web dashboard: a self-contained dark-theme single-page UI that
renders `/spec-loop` runs from the durable artifacts under `docs/spec-loop/<run-id>/`, with an
all-runs overview, a single-run drill-down (DAG/waves, slice table, status rollup, open
escalations, recent decisions), and near-real-time auto-refresh. Unlike the old per-invocation
server, this is a **machine-wide singleton** that **aggregates the runs of every repo you launch
it from** into one view — one container, one URL, all your sessions.

This command **mutates no run state** and **triggers no slice work**. It runs
`scripts/dashboard_launcher.py`, which prefers Docker and falls back to plain Python. The `Bash`
tool is now used to shell out to `docker` (dual-use: **build** the image on first run, **run** the
detached container, and **stop** it via `--stop`) — that is the honest capability boundary here.
Starting a container (or a foreground process) *is* a side effect; the read-only guarantee is about
your **run state**, which the dashboard physically cannot change: run artifacts are bind-mounted
`:ro` and the container drops all capabilities and runs non-root. There is no `Write`, `Edit`,
`Task`, or `AskUserQuestion` capability here, and that is the security boundary — keep it intact.

## Steps

1. **Start (or reuse) the dashboard.** Run, via `Bash`, from the repo whose runs you want included:

   ```
   python3 scripts/dashboard_launcher.py
   ```

   No `--port` flag exists — the singleton always publishes the fixed port `8787` on loopback.
   The launcher decides what to do:

   - **Docker daemon available and responsive → Docker path.** It launches (or reuses) one fixed
     machine-wide container named `spec-loop-dashboard`, then **prints the loopback URL and exits**
     — it does **not** hold your shell. The container is detached (`docker run -d`) and keeps
     serving after the command returns.
   - **Docker absent, not installed, or daemon down → Python fallback.** It prints a clear
     one-line message on stderr saying it fell back and *why* (e.g. `docker unavailable (docker not
     installed); falling back to a local foreground server`), then runs
     `python3 scripts/dashboard_server.py --root .` **in the foreground**. This path is fully
     functional — it *is* the listener — and stays attached until you stop it with `Ctrl-C`.

   On the **very first Docker invocation**, the launcher builds the image
   (`spec-loop-dashboard:local`) from the repo's `Dockerfile`; this can take tens of seconds. Later
   launches reuse the built image.

2. **Open the printed URL.** Visit `http://127.0.0.1:8787/` in a browser. The page loads the
   dark-theme UI, lists the runs from **every repo currently registered** (see below), and
   auto-refreshes with a visible freshness indicator. Click a run to drill into its DAG, waves,
   slice table, rollup, open escalations, and recent decisions. A run whose `dag.json` is
   momentarily half-written renders as a transient "state momentarily unreadable" card, never an
   error.

3. **Add more repos to the view (just run it there too).** Running the launcher from a *second*
   repo registers that repo and **recreates the shared singleton with the union** of per-root
   `:ro` mounts, so a single dashboard now serves runs from both repos. Docker has no in-place
   mount addition, so "attach + live updates from all sessions across repos" is realized precisely
   by this stop-and-recreate — which briefly **blips any open browsers** while the container cycles
   (a refresh reconnects them to the same URL).

4. **Stop the dashboard.**
   - **Docker path:** run `python3 scripts/dashboard_launcher.py --stop`. This is scoped to the
     singleton name **only** (`docker stop spec-loop-dashboard` then `docker rm spec-loop-dashboard`)
     — it never touches any other container and never uses an unscoped `rm -f`.
   - **Python-fallback path:** press `Ctrl-C` in the foreground terminal.

## Notes

- **Idempotent singleton.** There is exactly **one** machine-wide container name,
  `spec-loop-dashboard`. If it is already running with the current set of repos, re-running the
  launcher **reuses** it — it prints the URL and exits without starting a second container. Docker's
  `--name` uniqueness is the **authoritative** singleton lock: if two launches race, the loser sees
  a name-in-use error, treats it as "already up," reprints the URL, and exits `0` (it never starts a
  duplicate and never falls back to Python just because of the race).

- **Cross-repo aggregation via minimal `:ro` mounts.** Each registered repo contributes a single
  read-only bind mount of its `docs/spec-loop` directory — nothing else from the repo is mounted.
  **Stale roots are pruned** on each launch: a repo whose path was moved/deleted, or that has not
  been launched from in roughly the last 6 hours, drops out of the aggregated view so it does not
  drift or show ghost runs. There is **no** background reaper — pruning happens only when you run
  the launcher.

- **Read-only, by construction.** Run artifacts are mounted `:ro`, so the container **physically
  cannot write run state**. Exposure is **loopback-only** (`-p 127.0.0.1:8787:8787` — never a bare
  `0.0.0.0` publish). The container runs with `--cap-drop ALL` and non-root, and the Docker socket
  is **not** mounted. The machine-wide registry the launcher keeps under `~/.spec-loop/dashboard/`
  (which repos are registered, and the last-launched mount set) is **HOST metadata only** — it is
  **never mounted into the container**. Registry writes are best-effort: a lost update from a
  concurrent launch simply re-registers on the next launch, because Docker's `--name`, not this
  file, is the real lock.

- **Lifecycle honesty.** On the **Docker path** the command starts the detached container, prints
  the URL, and returns — it holds no shell, and the dashboard keeps serving in the background until
  `--stop`. On the **Python-fallback path** the command stays in the foreground because that process
  *is* the server. These are genuinely different lifecycles; know which one you got from the printed
  message.

- **Distinct from `/spec-loop:dashboard`.** `/spec-loop:dashboard` prints a one-shot
  **terminal-markdown** snapshot of a single run and starts no server. `dashboard-serve` is the
  **live web** dashboard — the richer, auto-refreshing, cross-repo HTML view. Use whichever fits:
  terminal for a quick glance at one run, web for a near-real-time, navigable view across all your
  sessions.

- **Single source of truth.** Waves and per-slice readiness labels are **derived** (never stored),
  using the exact rules of `/spec-loop:dashboard`; `dag.json` is the only authority for run state.
