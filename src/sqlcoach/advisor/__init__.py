"""Advisory layer.

Produces index recommendations, detects SQL anti-patterns, and hosts
the recommendation engine that aggregates findings from the analyzer
into ranked, explainable `Recommendation` objects. Introduced starting
Sprint 7.
"""

"""Advisor layer.

Turns analyzer findings and query structure into concrete, explainable
optimization advice: index recommendations (Sprint 7) and SQL
anti-pattern detection (Sprint 8). The recommendation engine (Sprint 9)
unifies this layer's output with the analyzer's into ranked
`Recommendation` objects.
"""