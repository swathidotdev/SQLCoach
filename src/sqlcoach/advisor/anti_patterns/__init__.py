"""SQL anti-pattern detection (Sprint 8).

Statically detects known SQL anti-patterns -- SELECT *, leading-wildcard
LIKE, ORDER BY RANDOM(), and N+1 query patterns -- purely from the
parsed SQL, with no database connection required (NFR-3.6.1). Detection
works on the sqlglot AST rather than fragile string matching (NFR-3.2).

The recommendation engine (Sprint 9) unifies these findings with the
plan analyzer's and the index advisor's into ranked `Recommendation`
objects.
"""