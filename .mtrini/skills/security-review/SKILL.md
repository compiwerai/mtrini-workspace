# Security Review

Think like an attacker, report like an engineer (severity + exploit path + fix).
Checklist:
1. Injection: SQL, shell, HTML/JS, template, path traversal (.. and symlink escapes), LDAP.
2. AuthN/AuthZ: every mutating route checks identity AND ownership; no IDOR by guessing ids.
3. Secrets: none in code/logs/URLs/bundles; keychain or env; rotate on exposure.
4. Dependencies: known CVEs (audit), pinned versions, minimal install; no copy-pasted crypto.
5. Transport: TLS everywhere outside localhost; cookies httpOnly+SameSite; CORS allowlists, not *.
6. Agent-specific: tool permission tiers, command classification, approval for destructive ops, transcript redaction.
Severity: critical (RCE/auth bypass) → high (data leak) → medium → low (hardening).
