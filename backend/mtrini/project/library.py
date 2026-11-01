"""Built-in skill library: ready-made SKILL.md instructions a user can add to a project in one click.

Each entry is {name, category, description, content}. Names are skill slugs (see SKILL_NAME).
"""
from __future__ import annotations

CATEGORIES = ("Code quality", "Testing", "Debugging", "Git", "Docs", "Frontend", "Backend", "Security",
              "Performance", "DevOps", "Data")

SKILLS: list[dict[str, str]] = [
    # ---------------- Code quality
    {"name": "code-review", "category": "Code quality",
     "description": "Review the current changes for bugs, risks and missing tests",
     "content": """1. Run `git diff` (and `git diff --cached`) to see what changed.
2. Read each changed file around the edits, not just the diff hunks.
3. List problems by severity: bugs first, then risky behavior, then missing tests, then style.
4. For each problem give the file and line, what goes wrong, and a concrete fix.
5. Do not edit files unless the user asks you to apply the fixes."""},
    {"name": "refactor", "category": "Code quality",
     "description": "Refactor a file or function without changing its behavior",
     "content": """1. Read the code the user names and everything that calls it.
2. Run the existing tests first and note the result, so you can prove nothing changed.
3. Make one kind of change at a time: rename, extract function, remove duplication, simplify conditionals.
4. Keep public names and signatures unless the user agreed to change them.
5. Run the tests again after each step. Stop and report if anything that passed now fails.
6. Summarize what changed and why it is easier to read now."""},
    {"name": "simplify", "category": "Code quality",
     "description": "Find code that can be shorter or clearer, and propose the simpler version",
     "content": """1. Look for: dead code, duplicated logic, needless abstraction, deep nesting, long parameter lists.
2. For each finding show the current code and the simpler version side by side.
3. Prefer the standard library and existing helpers over new code.
4. Do not change behavior. Mention any case where the simpler version would behave differently.
5. Apply the changes only when the user asks."""},
    {"name": "naming", "category": "Code quality",
     "description": "Suggest clearer names for variables, functions and files",
     "content": """1. Read the code and list names that are vague (data, tmp, handle, do_it), misleading, or inconsistent.
2. For each, propose a name that says what the thing is or does, following the project's naming style.
3. Check every place the name is used before renaming, including tests, docs and config.
4. Rename only when the user agrees, then run the tests."""},
    # ---------------- Testing
    {"name": "write-tests", "category": "Testing",
     "description": "Add focused tests for the code that was just changed",
     "content": """1. Find the project's test framework and where existing tests live.
2. Cover the changed behavior: the main path, edge cases and one failure case.
3. Follow the style of nearby tests. Do not add new test dependencies without asking.
4. Run the tests and fix failures in the tests (not the code) unless the code is wrong.
5. Report which tests you added and the final test result."""},
    {"name": "fix-failing-tests", "category": "Testing",
     "description": "Run the test suite, find why tests fail, and fix the cause",
     "content": """1. Find and run the project's test command (package.json scripts, pytest, cargo test, go test, and so on).
2. For each failure, read the assertion and the code under test before changing anything.
3. Decide whether the code or the test is wrong. Fix the code when the test describes the intended behavior.
4. Never delete or skip a test to make the suite pass.
5. Run the full suite again and report what failed, why, and what you changed."""},
    {"name": "test-coverage", "category": "Testing",
     "description": "Find important code paths that have no tests",
     "content": """1. If the project has a coverage tool, run it; otherwise compare source files with test files.
2. List untested areas ranked by risk: error handling, money or data changes, parsing, auth.
3. For the top three, describe the tests that would cover them.
4. Write those tests only if the user asks."""},
    {"name": "e2e-test", "category": "Testing",
     "description": "Write an end-to-end test for a user flow",
     "content": """1. Ask which flow to test if the user did not say (sign up, checkout, search...).
2. Use the end-to-end tool the project already has (Playwright, Cypress...). If none, propose one and wait for approval.
3. Write the steps like a user: open the page, fill fields, click, check what the user would see.
4. Prefer accessible selectors (roles, labels) over CSS classes.
5. Run the test and report the result."""},
    # ---------------- Debugging
    {"name": "debug", "category": "Debugging",
     "description": "Find the root cause of a bug before changing any code",
     "content": """1. Restate the bug: what happens, what should happen, and how to reproduce it.
2. Reproduce it yourself (run the command or test) and capture the exact error.
3. Form one hypothesis at a time and check it by reading code or adding a temporary log.
4. Once you know the root cause, explain it in two sentences before fixing.
5. Fix the cause, not the symptom, add a test that would have caught it, and remove temporary logs."""},
    {"name": "explain-error", "category": "Debugging",
     "description": "Explain an error message or stack trace in plain words",
     "content": """1. Read the error and the stack trace from the bottom frame of the user's own code.
2. Explain what the error means in one plain sentence.
3. Point to the exact file and line that triggers it and why.
4. Give the most likely fix, and a second possibility if the first is uncertain."""},
    {"name": "add-logging", "category": "Debugging",
     "description": "Add useful logs around a feature to make problems visible",
     "content": """1. Use the logging library the project already uses.
2. Log decisions and boundaries: inputs received, external calls and their results, errors with context.
3. Never log secrets, passwords, tokens or personal data.
4. Use levels: debug for detail, info for milestones, warning and error for problems.
5. Keep messages short and searchable."""},
    # ---------------- Git
    {"name": "commit-message", "category": "Git",
     "description": "Write a clear commit message for the staged changes",
     "content": """1. Run `git diff --cached`; if nothing is staged, use `git diff`.
2. Write a subject line under 60 characters in the imperative mood ("Add", "Fix").
3. Add a short body explaining why the change was made, if it is not obvious.
4. Show the message to the user. Do not commit unless they ask."""},
    {"name": "pr-description", "category": "Git",
     "description": "Write a pull request description from the branch's changes",
     "content": """1. Compare the branch with the main branch (`git log main..HEAD` and `git diff main...HEAD`).
2. Write: a one-line title, what changed and why, how it was tested, and anything reviewers should check.
3. List breaking changes and migrations separately, if there are any.
4. Keep it short. Show it to the user; do not open the PR yourself."""},
    {"name": "resolve-conflicts", "category": "Git",
     "description": "Resolve merge conflicts by understanding both sides",
     "content": """1. Run `git status` to list conflicted files.
2. For each conflict, read both versions and the commits that introduced them (`git log -p` on the file).
3. Combine the intent of both sides; do not just pick one.
4. Remove all conflict markers, then run the build and tests.
5. Explain each resolution in one line. Do not commit unless the user asks."""},
    # ---------------- Docs
    {"name": "explain-code", "category": "Docs",
     "description": "Explain how a file or feature works, for a new contributor",
     "content": """1. Read the file or feature the user names, and the code it calls.
2. Start with a two-sentence summary of what it does and why.
3. Walk through the main flow in order, naming functions and files.
4. Point out anything surprising: side effects, global state, known limitations.
5. Keep it short; offer to go deeper on any part."""},
    {"name": "write-readme", "category": "Docs",
     "description": "Write or update the README from what the project actually does",
     "content": """1. Read the code, package files and scripts; do not invent features.
2. Sections: what it is (one paragraph), install, run, configuration, tests, license.
3. Every command must be one you checked exists in the project.
4. Keep the existing README's content that is still true; mark anything you are unsure about.
5. Show the result before writing the file if a README already exists."""},
    {"name": "add-docstrings", "category": "Docs",
     "description": "Add short docstrings and comments where the code is not obvious",
     "content": """1. Document public functions and classes: what they do, their inputs, outputs and errors.
2. Explain why, not what: skip comments that repeat the code.
3. Match the project's docstring style (Google, NumPy, JSDoc, rustdoc...).
4. Do not change any code while documenting."""},
    {"name": "changelog", "category": "Docs",
     "description": "Write changelog entries for a release from the commits",
     "content": """1. List commits since the last tag (`git describe --tags --abbrev=0`, then `git log <tag>..HEAD`).
2. Group them: New, Changed, Fixed, Removed. Skip internal-only commits.
3. Write each entry for users, in plain words, saying what they can now do or what no longer breaks.
4. Show the entries; add them to CHANGELOG.md only if the user asks."""},
    # ---------------- Frontend
    {"name": "accessibility-check", "category": "Frontend",
     "description": "Check a page or component for accessibility problems and fix them",
     "content": """1. Check: every image has alt text, every control has a label, headings are in order, focus is visible.
2. Check keyboard use: everything reachable with Tab, Escape closes dialogs, no keyboard traps.
3. Check color contrast of text against its background (4.5:1 for body text).
4. List problems with the element and the fix; apply fixes when the user agrees."""},
    {"name": "responsive-layout", "category": "Frontend",
     "description": "Make a page work on phones, tablets and wide screens",
     "content": """1. Check the layout at 375px, 768px and 1440px wide.
2. Fix horizontal scrolling, text that overflows, tap targets smaller than 40px, and fixed widths.
3. Use the project's existing breakpoints and styling approach.
4. Report what changed at each size."""},
    # ---------------- Backend
    {"name": "api-endpoint", "category": "Backend",
     "description": "Add a new API endpoint following the project's existing patterns",
     "content": """1. Find two existing endpoints and copy their structure: routing, validation, errors, responses.
2. Validate all input; return clear errors with the right status codes.
3. Keep business logic out of the route handler if the project separates it.
4. Add tests for success, invalid input and not found / unauthorized.
5. Document the endpoint where the others are documented."""},
    {"name": "database-migration", "category": "Backend",
     "description": "Write a safe database migration for a schema change",
     "content": """1. Use the project's migration tool; never edit an already-applied migration.
2. Prefer additive changes: add columns as nullable or with defaults, backfill, then tighten.
3. Write the down migration, or explain why one is not possible.
4. Check indexes for new query patterns.
5. Explain the risk for existing data before the user runs it."""},
    # ---------------- Security
    {"name": "security-review", "category": "Security",
     "description": "Look for common security problems in the current changes",
     "content": """1. Check the diff for: injection (SQL, shell, HTML), missing auth checks, secrets in code, unsafe file paths, unsafe deserialization.
2. Check that user input is validated and output is escaped where it is rendered.
3. Check new dependencies for known problems and whether they are needed.
4. Report findings with severity, file and line, and a fix. Do not change code unless asked."""},
    {"name": "find-secrets", "category": "Security",
     "description": "Search the project for leaked keys, tokens and passwords",
     "content": """1. Search tracked files for patterns like API keys, tokens, private keys, passwords and connection strings.
2. Check .env files are git-ignored and that no secret appears in git history (`git log -p -S <pattern>`).
3. Report each finding with its file; never print the full secret, show only its first few characters.
4. Recommend rotating any secret that was ever committed."""},
    # ---------------- Performance
    {"name": "performance", "category": "Performance",
     "description": "Find and fix the slowest part of a feature, with measurements",
     "content": """1. Measure first: time the operation or use the project's profiler. Note the baseline.
2. Look for: repeated work in loops, N+1 queries, missing indexes, large payloads, blocking calls.
3. Change one thing at a time and measure again.
4. Keep the change only if it helps; report before and after numbers."""},
    # ---------------- DevOps
    {"name": "dockerize", "category": "DevOps",
     "description": "Add a Dockerfile to run the project in a container",
     "content": """1. Detect the language and how the project runs locally.
2. Write a small multi-stage Dockerfile: build stage, then a slim runtime image running as a non-root user.
3. Add a .dockerignore (node_modules, .git, .env, build output).
4. Pass configuration through environment variables, never bake secrets into the image.
5. Explain how to build and run it."""},
    {"name": "ci-pipeline", "category": "DevOps",
     "description": "Set up continuous integration that installs, tests and builds",
     "content": """1. Use the CI the project already has; if none, propose GitHub Actions.
2. Steps: check out, set up the runtime, install with a cache, lint, test, build.
3. Use the same commands developers run locally.
4. Pin action versions and keep secrets in the CI's secret store.
5. Explain what triggers the pipeline."""},
    # ---------------- Data
    {"name": "sql-query", "category": "Data",
     "description": "Write or explain a SQL query against the project's schema",
     "content": """1. Read the schema or models first so table and column names are real.
2. Write the query with explicit columns, clear joins and parameters instead of pasted values.
3. Explain what it returns and how it would behave on large tables (indexes, limits).
4. Never run queries that change data unless the user asks."""},
]


def library() -> list[dict[str, str]]:
    return SKILLS


def get(name: str) -> dict[str, str] | None:
    return next((s for s in SKILLS if s["name"] == name), None)
