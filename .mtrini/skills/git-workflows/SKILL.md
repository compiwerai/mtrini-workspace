# Git Workflows

History should read like a story.
- Commits: imperative subject (<72 chars), body explaining WHY; one logical change per commit.
- Never commit secrets, weights, .mtrini/secrets.json, or build output — check .gitignore first.
- Branches: short-lived feature branches off main; rebase to keep linear history; delete after merge.
- Before pushing: status → diff review → tests green → pull --rebase.
- Never rewrite public history (no force-push to shared branches); never auto-commit without being asked.
- Tags/releases: semver, changelog entry, artifact attached (e.g. Setup exe for desktop releases).
