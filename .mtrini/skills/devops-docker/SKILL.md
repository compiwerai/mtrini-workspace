# DevOps & Docker

Ship reproducible environments.
- Dockerfile: pinned base image, non-root user, .dockerignore, multi-stage builds for compiled assets.
- Compose: one command brings up app + deps; healthchecks; named volumes for data; secrets via env files (never baked into images).
- CI: lint → typecheck → test → build on every push; no secrets required for the base pipeline.
- Version artifacts (app likes MtriniWorkspace-Setup-X.Y.Z); keep a rollback path.
- Logs to stdout, config via environment, data in volumes — twelve-factor basics.
Verify locally with a clean checkout before touching CI config.
