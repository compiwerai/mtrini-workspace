# Code Review

Review diffs, not vibes. For every change verify:
1. Correctness: does it do what the author claims? Trace edge cases (empty, null, huge, concurrent).
2. Scope: no drive-by refactors; unrelated changes belong in another commit.
3. Safety: path confinement, secret handling, injection points (SQL/shell/HTML), auth checks.
4. Tests: new behavior has coverage; existing suite still passes — run it, don't trust CI badges.
5. Readability: names reveal intent; functions fit on one screen; no commented-out code.
Report verdicts as approve / request-changes / comment, with file:line references.
Never approve what you didn't read.
