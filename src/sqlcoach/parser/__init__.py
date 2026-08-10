"""Parsing layer.

Converts raw sources (SQL files, PostgreSQL log excerpts, and later
`pg_stat_statements` rows) into `Query` domain objects. The abstract
parser interface is introduced in Sprint 2 (US2.3); concrete parsers
are introduced in Sprint 3.
"""
