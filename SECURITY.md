# Security Policy

## Reporting

Do **not** open public issues for vulnerabilities. Contact the maintainers privately
with: affected version, reproduction steps, and impact. Expect acknowledgment within 5 business days.

## Secret handling

- API keys and HF tokens live in the OS keychain (`keyring`); fallback is
  `.mtrini/secrets.json` (0600, gitignored). They are never written to `config.json`,
  logs, diagnostics exports, or frontend bundles.
- Diagnostics export redacts values matching stored secrets.

## Execution security

- Filesystem access is confined to the workspace root (`security.resolve_inside`);
  `../../` escapes and symlink escapes are rejected.
- Commands are classified safe/risky/destructive; risky+ requires explicit approval in the UI.
- The agent never auto-commits; destructive file ops need confirmation.

## Provider security

API traffic goes only to explicitly configured providers/endpoints.
Custom base URLs are user-supplied and displayed before use.
