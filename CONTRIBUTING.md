# Contributing to Mtrini Workspace

## Setup

```bash
pip install -r backend/requirements.txt
npm install --prefix frontend
pytest backend/tests -q
npm test --prefix frontend
```

## Structure

- `backend/mtrini/` — `main.py` (API), `agent/` (loop), `tools/` (pluggable tools),
  `providers/` (pluggable providers), `models/` (registry), `project/` (.mtrini memory)
- `frontend/src/` — `App.tsx`, `components/`, `api/client.ts`
- `.mtrini/` — example project memory (skills, agents, instructions)

## Standards

- Python: typed, `ruff` clean, pytest for every new tool/provider.
- Frontend: TypeScript strict, accessible controls (labels, focus, ARIA), tests for new panels.
- Never commit secrets, model weights, or `.mtrini/secrets.json`.
- Keep agent changes minimal; verify with tests before claiming success.

## Adding a provider

1. Subclass the `ModelProvider` protocol (`chat/stream/list_models/supports_*`).
2. Register in `providers/registry.py` (+ `PROVIDER_META` entry).
3. Add tests with `respx` or the mock harness — no paid APIs in tests.

## Adding a tool

1. Append a `Tool(name, description, permission, schema, handler)` in `tools/`.
2. Permission must be one of `read|write|execute|network|destructive`.
3. Handlers receive the confined workspace root; use `security.resolve_inside`.

## Pull requests / issues

Describe what you inspected, changed, and how you verified (tests, build output).
Report security issues privately per `SECURITY.md`.
