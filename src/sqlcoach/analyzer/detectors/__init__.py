"""Execution-plan detectors.

Each module here contributes one `PlanDetector` implementation. The
default registry the analyzer uses is assembled in
`sqlcoach.analyzer.plan_analyzer.default_detectors()`; adding a new
detector means adding a module here and one line there -- no existing
detector or the analyzer itself is touched (Open/Closed Principle,
mirroring the Sprint 8 anti-pattern registry).
"""