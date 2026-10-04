# FastAPI Backend

Patterns for this stack (FastAPI + Pydantic v2 + asyncio).
- Routers return plain dicts/Pydantic models; errors via HTTPException with specific codes.
- Validate at the boundary (request models); never trust tool arguments — re-check paths and sizes inside handlers.
- Async I/O (httpx AsyncClient) for network; run blocking calls (subprocess, sqlite) in threads or keep them short.
- Long jobs stream via SSE with typed events; one-shot mutations return JSON.
- Secrets: keyring first, 0600 file fallback; never in config.json, logs, or responses. Redact in diagnostics.
- Every endpoint gets a TestClient test using tmp dirs — no real network in tests.
