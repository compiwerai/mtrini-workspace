# API Design

Design resources, not endpoints soup.
- Nouns for resources (/threads/{id}/messages), verbs in HTTP methods; nested only one level deep.
- Consistent envelopes: data on success, {detail} + proper status on failure (400 validation, 404 missing, 422 semantic, 502 upstream).
- Pagination (limit/cursor), filtering, and field selection from day one for list routes.
- Versioning: additive changes don't need a version bump; breaking ones do — and get a migration note.
- Streaming (SSE) for long operations with typed events; always send a terminal event (done/error).
- Document every route in docs/API.md with method, body, and an example.
