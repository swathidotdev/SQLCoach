"""Impact estimation (US11.4, FR-4.5).

Estimates the expected improvement of a missing-index recommendation
from the one hard number we have: the rows the sequential scan actually
examines (from the plan finding's ANALYZE metrics).

The estimate is deliberately order-of-magnitude, never a fabricated
millisecond figure (NFR-4.2): we know how many rows are scanned now, and
that an index turns a full scan into a targeted seek, but the exact
after-cost depends on selectivity we can't measure without creating the
index. So every estimate is framed as a reduction in *rows read*, scaled
by table size, and carries a mandatory "verify by re-running EXPLAIN
ANALYZE" caveat.
"""

from __future__ import annotations

from typing import NamedTuple

_HIGH_ROWS = 100_000
_MODERATE_ROWS = 1_000

_VERIFY = (
    "Estimate only; verify by creating the index and re-running EXPLAIN ANALYZE."
)


class ImpactEstimate(NamedTuple):
    """A quantified-but-honest impact estimate.

    Attributes:
        text: The human-readable estimate, for `Recommendation.expected_impact`.
        magnitude: A coarse bucket ("high" / "moderate" / "low") from the
            rows-examined size, available for future ranking use.
    """

    text: str
    magnitude: str


def estimate_index_impact(rows_examined: int) -> ImpactEstimate:
    """Estimate the impact of adding an index, from rows currently scanned."""
    if rows_examined >= _HIGH_ROWS:
        magnitude = "high"
        scale = (
            "a large reduction in rows read -- often one to several orders of "
            "magnitude for a selective filter"
        )
    elif rows_examined >= _MODERATE_ROWS:
        magnitude = "moderate"
        scale = "a substantial reduction in rows read for a selective filter"
    else:
        magnitude = "low"
        scale = (
            "a modest reduction; the table is small enough that the current scan "
            "may already be acceptable"
        )

    text = (
        f"Currently examines ~{rows_examined:,} rows per execution; an index lets "
        f"PostgreSQL seek directly to matching rows instead of scanning the table -- "
        f"{scale}. {_VERIFY}"
    )
    return ImpactEstimate(text=text, magnitude=magnitude)