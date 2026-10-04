# SQL & Databases

Model data explicitly, migrate safely.
- Schema: primary keys, foreign keys with ON DELETE rules, NOT NULL by default, check constraints for invariants.
- Queries: parameterized always; SELECT only needed columns; EXPLAIN before adding indexes; index foreign keys and frequent filters.
- Migrations: forward-only, reversible when possible, backfill in batches; test migrate+rollback on a copy.
- SQLite specifics: WAL mode for concurrent readers, single writer discipline, VACUUM after big deletes.
- Never store secrets, tokens, or PII in plaintext — hash passwords (argon2/bcrypt), encrypt the rest at the app layer.
