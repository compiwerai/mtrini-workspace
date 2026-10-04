# Documentation

Write docs the reader needs, in this order: what it is, how to run it, how it works, how to extend it.
- README: one-page tour (install → run → configure → test). No marketing fluff.
- Code: docstrings on public functions, comments only for WHY (invariants, workarounds with links).
- API changes update docs/API.md in the same commit as the code.
- Examples must be executed or generated, never hand-typed and unverified.
- Keep a changelog habit: what changed, why, how to migrate.
Match the repo's voice: short sentences, commands in code blocks, honest limitations section.
