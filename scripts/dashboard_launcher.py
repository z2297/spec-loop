#!/usr/bin/env python3
"""Docker-preferred / python-fallback launcher for the spec-loop dashboard.

Launches a machine-wide SINGLETON dashboard container (fixed name, fixed port)
that runs the EXISTING ``scripts/dashboard_server.py`` (via the s2 image), then
EXITS — it does not hold a shell. When Docker is unavailable (not installed or
the daemon is down) it falls back to running the server directly in the
foreground. Docker teardown is via ``--stop``.

Two clean layers mirror ``dashboard_server.py`` and ``pr_resolver.py``:

  (A) PURE, importable functions with NO subprocess and NO live daemon — every
      argv builder, the registry parse/prune logic, the mount-composition
      helpers, the stdout parsers, and the ``plan_launch`` decision. All are
      unit-tested without Docker. (Registry/mountset read/write do touch the
      host filesystem — see their own docstrings — but never docker.)

  (B) A thin side-effect shell — ``_run`` (the sole subprocess entry point) and
      its callers (``main``, ``_launch``/``_build_plan``/``_run_plan``/
      ``_execute_plan``, ``_stop``, ``_daemon_available``, and the foreground
      ``_fallback`` which hands off via ``os.execvp``). ``_run`` is adapted from
      ``pr_resolver._run`` (``subprocess.run(..., shell=False, check=False,
      capture_output=True, text=True)`` with a ``FileNotFoundError`` guard) and
      returns the CompletedProcess.

CRITICAL mount composition: ``dashboard_server._resolve_roots`` ALWAYS appends
``docs/spec-loop`` to whatever ``--root`` it receives. So the launcher mounts the
HOST ``<root>/docs/spec-loop`` at the container path
``<container_root>/docs/spec-loop`` and passes ``--root <container_root>`` — the
server's own ``+docs/spec-loop`` join then lands exactly on the mounted
artifacts (never a nonexistent double path).

Usage:
    python3 scripts/dashboard_launcher.py            # start-or-reuse the singleton
    python3 scripts/dashboard_launcher.py --stop     # tear the singleton down
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dashboard_server import DEFAULT_PORT, DATA_SUBPATH, _root_keys  # noqa: E402


# --- constants (fixed-name / fixed-port machine-wide singleton) ---
SINGLETON_NAME = "spec-loop-dashboard"
IMAGE_TAG = "spec-loop-dashboard:local"
STATE_DIR = os.path.expanduser("~/.spec-loop/dashboard")
REGISTRY_NAME = "registry.json"
# A root not seen in this window is presumed abandoned and reaped from the
# aggregated singleton (6 hours — long enough to survive a lunch break, short
# enough that a closed repo stops being served the same day).
STALE_SECONDS = 6 * 60 * 60
# In-container root under which each host artifact dir is mounted. The leaf is
# s1's stable per-root key, so /roots/<root_key>/docs/spec-loop holds the runs.
CONTAINER_ROOT_BASE = "/roots"
DATA_REL = "/".join(DATA_SUBPATH)  # "docs/spec-loop"
# The repo checkout that holds the Dockerfile — the build context is pinned here,
# never an arbitrary machine-wide cwd. This file lives in <checkout>/scripts/.
CONTEXT_DIR = str(Path(__file__).resolve().parent.parent)


# ==========================================================================
# Layer (A): pure daemon / image predicates
# ==========================================================================

def parse_daemon_available(returncode):
    """``docker info`` returning rc 0 means the daemon is reachable."""
    return returncode == 0


def parse_image_present(stdout):
    """``docker images -q <tag>`` prints an image id when present, nothing when
    absent. Non-empty (whitespace-stripped) stdout => the image exists."""
    return bool(stdout.strip())


# ==========================================================================
# Layer (A): host-only registry (JSON {realpath(root): last_seen_epoch})
# ==========================================================================

def _registry_path(state_dir):
    return os.path.join(state_dir, REGISTRY_NAME)


def _sanitize_registry(data):
    """Keep only ``{str: number}`` entries from a decoded payload.

    A non-dict payload degrades to ``{}``; within a dict, any entry whose value
    is not an int/float (bool is excluded — it is an int subclass) is dropped so
    the returned map upholds the ``{root: numeric last_seen}`` invariant and can
    never make ``prune_stale``'s numeric comparison raise ``TypeError``."""
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)}


def read_registry(state_dir):
    """Load the registry map, or ``{}`` if absent/corrupt (never crash).

    HOST-only metadata — this file is NEVER mounted into the container. A
    non-dict payload (or non-JSON) degrades to empty, and any entry with a
    non-numeric ``last_seen`` is dropped, rather than propagating a malformed
    shape downstream. A corrupt/unreadable file emits a one-line stderr warning
    so the reset (and the resulting loss of other roots) is OBSERVABLE."""
    try:
        with open(_registry_path(state_dir), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as err:
        print(f"warning: registry at {_registry_path(state_dir)} unreadable "
              f"({err}); starting fresh", file=sys.stderr)
        return {}
    return _sanitize_registry(data)


def write_root_entry(state_dir, root, now):
    """Best-effort read-modify-write of ``{realpath(root): now}`` (creates the
    state dir as needed). Lost updates on a concurrent write are tolerated — a
    dropped root simply re-registers on its next launch; Docker's ``--name``
    uniqueness, not this file, is the authoritative singleton lock."""
    os.makedirs(state_dir, exist_ok=True)
    registry = read_registry(state_dir)
    registry[os.path.realpath(str(root))] = now
    with open(_registry_path(state_dir), "w", encoding="utf-8") as fh:
        json.dump(registry, fh)


def prune_stale(registry, now, cutoff, path_exists):
    """Return the surviving subset of ``registry``.

    Drops an entry for EITHER independent reason: its timestamp is older than
    ``now - cutoff``, OR its ``<root>/docs/spec-loop`` fails the injected
    ``path_exists`` callable (the repo was moved/deleted). Both drop reasons are
    load-bearing and kept separate."""
    survivors = {}
    for root, last_seen in registry.items():
        if last_seen < now - cutoff:
            continue
        if not path_exists(os.path.join(root, DATA_REL)):
            continue
        survivors[root] = last_seen
    return survivors


def desired_roots(registry, now, cutoff, path_exists):
    """The sorted, realpath-deduped list of surviving host root paths."""
    survivors = prune_stale(registry, now, cutoff, path_exists)
    return sorted({os.path.realpath(r) for r in survivors})


# ==========================================================================
# Layer (A): mount composition (the architect BLOCKER fix)
# ==========================================================================

def mount_point_for(root_key):
    """The in-container ROOT path for a root key (``/roots/<root_key>``).

    This is the value passed to ``--root`` — NOT the mount target. The server
    appends ``docs/spec-loop`` to it, so the artifacts must be mounted at
    ``mount_target_for(...)`` (below), not here."""
    return f"{CONTAINER_ROOT_BASE}/{root_key}"


def mount_source_for(host_root):
    """The HOST side of the bind mount: ``<host_root>/docs/spec-loop``."""
    return os.path.join(str(host_root), DATA_REL)


def mount_target_for(root_key):
    """The CONTAINER side of the bind mount: ``<container_root>/docs/spec-loop``,
    which composes with the server's ``--root <container_root>`` + its own
    ``docs/spec-loop`` join so the read artifacts land exactly here."""
    return f"{mount_point_for(root_key)}/{DATA_REL}"


def _container_roots(roots):
    """Map an ordered list of host roots to ``(host_root, root_key)`` pairs using
    s1's ``_root_keys`` (never a parallel naming scheme)."""
    return list(zip(roots, _root_keys(roots)))


# ==========================================================================
# Layer (A): docker argv builders (lists only — never shell strings)
# ==========================================================================

def build_image_argv(tag, context_dir):
    """``docker build -t <tag> -f <context>/Dockerfile <context>`` — the build
    context pinned to the repo checkout that holds the Dockerfile."""
    dockerfile = os.path.join(str(context_dir), "Dockerfile")
    return ["docker", "build", "-t", tag, "-f", dockerfile, str(context_dir)]


def build_image_present_argv():
    """``docker images -q <tag>`` — prints the image id when present."""
    return ["docker", "images", "-q", IMAGE_TAG]


def build_running_names_argv():
    return ["docker", "ps", "--format", "{{.Names}}"]


def build_all_names_argv():
    return ["docker", "ps", "-a", "--format", "{{.Names}}"]


def parse_running_names(stdout):
    """Set of container names from ``docker ps --format {{.Names}}`` output."""
    return {line.strip() for line in stdout.splitlines() if line.strip()}


def parse_all_names(stdout):
    """Set of container names from ``docker ps -a --format {{.Names}}`` output."""
    return {line.strip() for line in stdout.splitlines() if line.strip()}


def build_run_argv(name, image, port, roots):
    """Full ``docker run -d`` argv for the singleton.

    Security-critical invariants (asserted in the tests):
      * publish loopback only — ``-p 127.0.0.1:{port}:{port}`` (NEVER bare
        ``{port}:{port}``), and the host-side port equals ``--advertise-port``;
      * one read-only mount per root — ``-v <src>:<target>:ro`` where
        ``<target>`` composes as ``<container_root>/docs/spec-loop``;
      * ``--cap-drop ALL``; NO ``--privileged``, NO ``--user 0``/root, NO
        docker.sock mount;
      * ``--bind-host`` only ever ``0.0.0.0``; ``--advertise-port`` never ``*``.

    The server args are a FRESH command (they fully replace the image's baked
    default CMD, they do not append). ``roots`` is the list of HOST root paths;
    container roots are derived via ``_root_keys`` + ``mount_point_for``."""
    pairs = _container_roots(roots)
    argv = ["docker", "run", "-d", "--name", name,
            "-p", f"127.0.0.1:{port}:{port}", "--cap-drop", "ALL"]
    for host_root, root_key in pairs:
        argv += ["-v", f"{mount_source_for(host_root)}:"
                 f"{mount_target_for(root_key)}:ro"]
    argv += [image, "python3", "scripts/dashboard_server.py",
             "--bind-host", "0.0.0.0",
             "--port", str(port), "--advertise-port", str(port)]
    for _host_root, root_key in pairs:
        argv += ["--root", mount_point_for(root_key)]
    return argv


def build_stop_argv(name):
    """``docker stop <name>`` — targets the fixed singleton name ONLY."""
    return ["docker", "stop", name]


def build_rm_argv(name):
    """``docker rm <name>`` — targets the fixed singleton name ONLY (no ``-f`` on
    an unscoped target)."""
    return ["docker", "rm", name]


def build_teardown_argvs(name):
    """The shared scoped stop+rm sequence reused by BOTH ``--stop`` and the
    RECREATE path — always name-scoped, never an unscoped ``rm -f``."""
    return [build_stop_argv(name), build_rm_argv(name)]


# ==========================================================================
# Layer (A): pure launch decision
# ==========================================================================

# Decision tokens for plan_launch.
FALLBACK = "fallback"
BUILD_CREATE = "build_create"
CREATE = "create"
RECREATE = "recreate"
REUSE = "reuse"


def plan_launch(daemon_available, image_present, running_names, all_names,
                current_roots, desired):
    """Pure launch decision — returns ``(decision, [argv, ...])``.

    Inputs are plain data (no subprocess), so this is fully unit-testable:
      * ``daemon_available`` — from ``parse_daemon_available``;
      * ``image_present`` — from ``parse_image_present``;
      * ``running_names`` / ``all_names`` — from the ps parsers;
      * ``current_roots`` — the singleton's current container-root set (or None
        when it is not running);
      * ``desired`` — the desired HOST root list (already pruned/sorted).

    Decisions, in precedence order:
      FALLBACK      no daemon -> run the server directly (no argv).
      BUILD_CREATE  image absent -> build, then run.
      RECREATE      singleton exists-but-stopped, OR its root set changed ->
                    scoped stop+rm, then run.
      CREATE        no singleton at all -> run.
      REUSE         running with an unchanged root set -> nothing to do.
    """
    if not daemon_available:
        return FALLBACK, []
    run = build_run_argv(SINGLETON_NAME, IMAGE_TAG, DEFAULT_PORT, desired)
    if not image_present:
        return BUILD_CREATE, [build_image_argv(IMAGE_TAG, CONTEXT_DIR), run]
    is_running = SINGLETON_NAME in running_names
    exists = SINGLETON_NAME in all_names
    if is_running and current_roots == desired:
        return REUSE, []
    if exists:
        return RECREATE, build_teardown_argvs(SINGLETON_NAME) + [run]
    return CREATE, [run]


# ==========================================================================
# Layer (B): thin side-effect shell
# ==========================================================================

def _run(argv):
    """Run one command via list-args (shell=False). Sole subprocess entry point —
    adapted from ``pr_resolver._run`` so the no-shell-injection guarantee is
    provable in one place. Returns the ``subprocess.CompletedProcess`` (adapted,
    not verbatim: callers read ``.returncode``/``.stdout``/``.stderr``); raises
    ``FileNotFoundError`` (via subprocess) when the binary is absent, which the
    caller treats as 'docker not installed -> fall back'."""
    return subprocess.run(
        argv, shell=False, check=False, capture_output=True, text=True,
    )


def _loopback_url(port):
    return f"http://127.0.0.1:{port}/"


def _name_conflict(stderr):
    """True when a ``docker run`` failed because the fixed name is already in use
    (someone else won the race — the singleton is already up)."""
    lowered = stderr.lower()
    return "is already in use" in lowered or "already in use by container" in lowered


def _port_bound(stderr):
    """True when a ``docker run`` failed because the published port is taken."""
    lowered = stderr.lower()
    return ("address already in use" in lowered
            or "port is already allocated" in lowered
            or "bind for" in lowered)


def _fallback(reason):
    """Run the server directly in the FOREGROUND (docker absent / daemon down).

    Prints a clear one-line message saying it fell back and WHY, then hands the
    process off to the server via ``os.execvp`` so its live output (startup URL,
    banner, errors) reaches the terminal and Ctrl-C works natively. The server
    path is ABSOLUTE (pinned to this checkout, like the docker build context) so
    it launches from any cwd; ``--root`` is the ABSOLUTE cwd the user invoked
    from (the server confines reads within it). This path does NOT write the
    registry (the registry describes the container's mount set). ``execvp``
    replaces this process, so the flushed message is the last thing the launcher
    itself prints."""
    print(f"docker unavailable ({reason}); "
          f"falling back to a local foreground server", file=sys.stderr, flush=True)
    server = os.path.join(CONTEXT_DIR, "scripts", "dashboard_server.py")
    argv = ["python3", server, "--root", os.path.abspath(os.getcwd())]
    os.execvp(argv[0], argv)


def _daemon_available():
    """Probe the daemon; a missing ``docker`` binary => unavailable (not a crash)."""
    try:
        return parse_daemon_available(_run(["docker", "info"]).returncode)
    except FileNotFoundError:
        return None  # binary absent — distinct fallback reason


def _handle_run_failure(proc, port):
    """Interpret a failed ``docker run``. A name-conflict means the singleton is
    already up (reuse, exit 0 — NEVER python fallback, NEVER an unscoped rm -f);
    a port-bound failure is a clear actionable message; anything else surfaces
    the daemon's own stderr."""
    if _name_conflict(proc.stderr):
        print(f"dashboard singleton already running; open {_loopback_url(port)}")
        return 0
    if _port_bound(proc.stderr):
        print(f"cannot start dashboard: port {port} is busy "
              f"(another process is bound to it)", file=sys.stderr)
        return 1
    print(f"docker run failed: {proc.stderr.strip()}", file=sys.stderr)
    return 1


def _no_such_container(stderr):
    """True when a scoped ``docker stop``/``rm`` failed only because the target is
    already gone — a benign race, not a real failure."""
    return "no such container" in stderr.lower()


def _execute_plan(decision, argvs, port):
    """Run a non-REUSE plan's argv sequence. The LAST argv is the ``docker run``;
    its failure is interpreted; every earlier step (build/stop/rm) must succeed
    first. A teardown step (stop/rm) that fails only with 'No such container' is
    TOLERATED (a benign race — the container is already gone) and does not abort
    the plan. Empty ``argvs`` never reaches the ``docker run`` step. Returns
    ``(exit_code, ran_ok)``."""
    if not argvs:
        return _fallback("docker daemon not responding"), False
    for argv in argvs[:-1]:
        proc = _run(argv)
        if proc.returncode != 0 and not _no_such_container(proc.stderr):
            print(f"{' '.join(argv[:2])} failed: {proc.stderr.strip()}",
                  file=sys.stderr)
            return 1, False
    run_proc = _run(argvs[-1])
    if run_proc.returncode != 0:
        return _handle_run_failure(run_proc, port), False
    return 0, True


MOUNTSET_NAME = "mountset.json"


def _mountset_path(state_dir):
    return os.path.join(state_dir, MOUNTSET_NAME)


def read_mount_set(state_dir):
    """The container-root set the singleton was LAST launched with, or ``None``
    if unknown. Docker cannot report this set back, so the launcher records it
    on each successful run; comparing it against the freshly-computed desired set
    is what distinguishes REUSE from RECREATE-on-root-change."""
    try:
        with open(_mountset_path(state_dir), "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as err:
        print(f"warning: mountset at {_mountset_path(state_dir)} unreadable "
              f"({err}); treating as unknown", file=sys.stderr)
        return None
    return list(data) if isinstance(data, list) else None


def write_mount_set(state_dir, roots):
    os.makedirs(state_dir, exist_ok=True)
    with open(_mountset_path(state_dir), "w", encoding="utf-8") as fh:
        json.dump(list(roots), fh)


def _launch(now):
    """The docker-preferred launch path. Returns the process exit code.

    Registers this repo in the host registry BEFORE computing the plan so that
    the freshly-launched singleton mounts it too; this pre-registration is
    intentional and benign — a run that later fails simply leaves a timestamp
    that self-expires via ``prune_stale``. The mount set (the container's actual
    contents) is recorded only after a successful run. A missing binary or a
    down daemon falls back to the foreground server; both distinguished by
    reason. Prints the loopback URL and EXITS (does not hold a shell)."""
    available = _daemon_available()
    if available is None:
        return _fallback("docker not installed")
    if not available:
        return _fallback("docker daemon not responding")
    write_root_entry(STATE_DIR, os.getcwd(), now)  # register this repo first
    registry = read_registry(STATE_DIR)
    desired = desired_roots(registry, now, STALE_SECONDS, os.path.exists)
    plan = _build_plan(available, desired)
    return _run_plan(plan, desired)


def _build_plan(available, desired):
    """Gather live docker state and compute the pure plan (no execution).

    A RUNNING singleton is REUSE only when its recorded mount set (from
    ``read_mount_set``) equals the freshly-computed ``desired`` — otherwise a
    newly-registered root must trigger a RECREATE. When the singleton is not
    running, ``current_roots`` is None so ``plan_launch`` never reports REUSE."""
    image_present = parse_image_present(_run(build_image_present_argv()).stdout)
    running = parse_running_names(_run(build_running_names_argv()).stdout)
    all_names = parse_all_names(_run(build_all_names_argv()).stdout)
    current = read_mount_set(STATE_DIR) if SINGLETON_NAME in running else None
    return plan_launch(available, image_present, running, all_names,
                       current, desired)


def _run_plan(plan, desired):
    decision, argvs = plan
    port = DEFAULT_PORT
    if decision == REUSE:
        print(f"dashboard already running; open {_loopback_url(port)}")
        return 0
    # Belt-and-suspenders: FALLBACK (or any empty plan) must never reach
    # _execute_plan, whose last-argv interpretation assumes a docker run.
    if decision == FALLBACK or not argvs:
        return _fallback("docker daemon not responding")
    code, ran_ok = _execute_plan(decision, argvs, port)
    if ran_ok:
        write_mount_set(STATE_DIR, desired)  # record what the singleton now runs
        print(f"dashboard {decision}; open {_loopback_url(port)}")
    return code


def _stop():
    """Tear the singleton down via the scoped stop+rm sequence (name-scoped only).

    Honest about outcomes: a benign 'No such container' (already gone) is
    tolerated, but any OTHER stop/rm failure surfaces the daemon's stderr and
    returns nonzero — 'stopped' is claimed only when the container is actually
    gone. A missing ``docker`` binary is reported, not crashed on."""
    try:
        for argv in build_teardown_argvs(SINGLETON_NAME):
            proc = _run(argv)  # rm after stop; 'no such container' is benign
            if proc.returncode != 0 and not _no_such_container(proc.stderr):
                print(f"{' '.join(argv[:2])} failed: {proc.stderr.strip()}",
                      file=sys.stderr)
                return 1
    except FileNotFoundError:
        print("docker not installed; nothing to stop", file=sys.stderr)
        return 1
    print(f"stopped dashboard singleton {SINGLETON_NAME!r}")
    return 0


def main(argv=None):
    """Parse ONLY ``--stop`` (no ``--port`` — fixed-name/fixed-port singleton),
    then either tear down or launch. Docker-path errors are interpreted; a
    missing docker binary or a down daemon falls back to the foreground server."""
    ap = argparse.ArgumentParser(
        description="Docker-preferred / python-fallback dashboard launcher")
    ap.add_argument("--stop", action="store_true",
                    help="stop and remove the singleton dashboard container")
    args = ap.parse_args(argv)
    if args.stop:
        return _stop()
    import time
    return _launch(time.time())


if __name__ == "__main__":
    sys.exit(main())
