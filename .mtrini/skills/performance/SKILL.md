# Performance

Measure first, optimize the hot path, re-measure.
1. Profile (cProfile/py-spy, browser devtools, EXPLAIN ANALYZE) — never guess the bottleneck.
2. Algorithmic wins beat micro-optimizations: N+1 queries, repeated I/O, unindexed scans.
3. Cache at the right layer: memoize pure calls, HTTP cache headers, DB query cache — with invalidation rules.
4. Frontend: code-split routes, virtualize long lists, debounce search, avoid layout thrash.
5. Backend: connection pooling, pagination everywhere, stream large responses, background heavy jobs.
6. Report before/after numbers (p50/p95, bundle KB) with the same workload.
Correctness and readability outrank speed until numbers prove otherwise.
