# Minimal image for the spec-loop read-only dashboard.
#
# Runs the EXISTING scripts/dashboard_server.py (single source of truth — no forked
# or reimplemented server). Pure Python stdlib, so no `pip install` and no build
# toolchain: this honors the repo's zero-third-party-dependency identity. The UI
# assets are baked IN (not mounted) so the server and UI versions never drift.
#
# REQUIRED RUN CONTRACT (enforced by the launcher, slice s3 — NOT baked here):
#   * publish loopback only:      -p 127.0.0.1:PORT:PORT   (never 0.0.0.0 on the host)
#   * mount artifact roots read-only:  -v /repo:/repo:ro    (and pass --root /repo)
#   * drop all capabilities:      --cap-drop ALL
#   * keep it unprivileged:       no --privileged, no --user 0, no docker.sock mount
#   * advertised port:            s3 passes --advertise-port to match the published
#                                 port (drives the Host allowlist). This image does
#                                 NOT set it, so the allowlist defaults to the bound
#                                 port and is never widened by the 0.0.0.0 bind.
#
# The default CMD binds 0.0.0.0 (required so a mapped port is reachable inside the
# container) but passes NO --root, so cwd defaults to /app and /app/docs/spec-loop
# does not exist in the image. The server starts healthy (prints a stderr warning)
# and serves ZERO runs until s3 bind-mounts an artifact root :ro and passes
# --root <mounted-path> — an empty dashboard here is expected, not a defect.
#
# Image reproducibility (digest-pinning the base) is intentionally out of scope for
# this minimal, local-use image. The 3.12-slim tag matches the Python version CI
# exercises (.github/workflows/validate.yml pins 3.12).

FROM python:3.12-slim

# Unprivileged runtime user — the container must NOT run as root.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

# Bake in ONLY the runtime files: the server and its UI assets. build_server
# resolves assets via Path(__file__).resolve().parent / "dashboard_assets", so
# keeping the script and dashboard_assets/ co-located under /app/scripts/ works
# unchanged.
COPY scripts/dashboard_server.py scripts/dashboard_server.py
COPY scripts/dashboard_assets/ scripts/dashboard_assets/

# Documentation only (does not publish the port; s3 does the -p mapping).
EXPOSE 8787

USER app

# Run the existing server, bound to 0.0.0.0 so a mapped host port is reachable.
# No --advertise-port and no --root here (see run contract above): s3 supplies both
# at runtime. Keep the interpreter as `python3` to match the repo's convention.
CMD ["python3", "scripts/dashboard_server.py", "--bind-host", "0.0.0.0", "--port", "8787"]
