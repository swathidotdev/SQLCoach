"""SQLCoach — PostgreSQL-first SQL performance analyzer and index advisor.

Importing this package must have no side effects: no logging configuration,
no file I/O, and no network access (NFR-1.4). Explicit initialization
(configuration loading, logging setup) is performed via dedicated entry
points introduced in later Sprint 1 stories (US1.2, US1.3), not at import
time.
"""

__version__ = "0.1.0"
