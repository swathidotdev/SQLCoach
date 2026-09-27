"""DROP INDEX statement generation (Sprint 11).

Generates the DROP statement for an index-hygiene recommendation. As
with CREATE INDEX, SQLCoach only ever *generates* this text and never
executes it (NFR-3.5.1) -- dropping an index is destructive, so it is
always left for the user to run after verification.
"""

from __future__ import annotations


def generate_drop_index(index_name: str) -> str:
    """Return a DROP INDEX statement for the named index.

    The name is emitted unquoted (correct for ordinary lowercase names)
    and unqualified (assumes the search_path). The recommendation text
    suggests DROP INDEX CONCURRENTLY, which can't be generated as a
    single canned statement here because it cannot run inside a
    transaction -- that nuance is left to the user.
    """
    return f"DROP INDEX {index_name};"