"""Database layer.

Owns all PostgreSQL connectivity via psycopg3: connection management,
`EXPLAIN ANALYZE` execution, and system-catalog / `pg_stat_statements`
access. Exposes a repository-style interface so the analyzer and
advisor never depend on the driver directly (FR-2.6). Introduced
starting Sprint 2.
"""
