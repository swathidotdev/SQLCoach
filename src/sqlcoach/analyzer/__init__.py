"""Analysis layer.

Inspects `ExecutionPlan` objects and query structure to detect
performance problems: sequential scans, inefficient joins, expensive
sorts, and cardinality misestimation. Introduced starting Sprint 6.
"""
