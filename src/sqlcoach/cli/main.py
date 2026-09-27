"""SQLCoach CLI entry point.

This module owns only argument parsing, input validation, invoking
application services, and output formatting (NFR-X.2). Business logic
must never live here -- every command below collects its arguments,
calls exactly one service function, and renders the result (FR-2.10).

It is also the single place where domain errors are translated into
user-facing messages and process exit codes (FR-2.9). Nothing below
the CLI needs to know about exit codes, and nothing above the service
layer should ever see a traceback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import typer

from sqlcoach.config import Settings, load_settings
from sqlcoach.exceptions import (
    ConfigError,
    DatabaseConnectionError,
    MutatingStatementError,
    ParsingError,
    SQLCoachError,
    ValidationError,
)
from sqlcoach.logging_config import configure_logging
from sqlcoach.reports.comparison import ComparisonResult, compare_service
from sqlcoach.reports.services import (
    AnalyzeResult,
    NotYetImplementedError,
    analyze_service,
    audit_service,
    report_service,
)

app = typer.Typer(
    name="sqlcoach",
    help="PostgreSQL-first SQL performance analyzer and index advisor.",
    no_args_is_help=True,
)

# Exit-code map (FR-2.9). Exit code 2 is deliberately absent: Click
# (and therefore Typer) already reserves it for usage errors such as a
# missing argument, and reusing it would make "you typed the command
# wrong" indistinguishable from a real failure in a CI log. New error
# types are added here without touching any command function.
_EXIT_CODES: dict[type[SQLCoachError], int] = {
    ConfigError: 1,
    ValidationError: 3,
    ParsingError: 4,
    DatabaseConnectionError: 5,
    MutatingStatementError: 6,
}
_DEFAULT_ERROR_EXIT_CODE = 1


def _exit_code_for(error: SQLCoachError) -> int:
    """Return the exit code for `error`, matching the most specific type first."""
    for error_type, code in _EXIT_CODES.items():
        if isinstance(error, error_type):
            return code
    return _DEFAULT_ERROR_EXIT_CODE


@app.callback()
def main(
    ctx: typer.Context,
    config_file: Optional[Path] = typer.Option(
        None,
        "--config",
        help="Path to a sqlcoach.toml config file. Defaults to ./sqlcoach.toml if present.",
    ),
    json_logs: bool = typer.Option(
        False,
        "--json-logs",
        help="Emit structured JSON logs instead of human-readable text.",
    ),
) -> None:
    """Load settings and configure logging before any subcommand runs.

    The loaded Settings are stashed on the Typer context so each command
    reuses this single, precedence-correct load (defaults < file < env)
    rather than reloading -- keeping --config honored everywhere.
    """
    try:
        settings = load_settings(config_file)
        # A --json-logs flag on the command line always wins over config/env,
        # since it represents the most specific, most recently expressed intent.
        configure_logging(
            level=settings.log_level, json_output=json_logs or settings.json_logs
        )
    except SQLCoachError as exc:
        typer.secho(f"Configuration error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=_exit_code_for(exc)) from exc

    ctx.obj = settings


def _settings_from(ctx: typer.Context) -> Settings:
    """Return the Settings the callback loaded for this invocation."""
    # ctx.obj is always set by the callback above before any command runs.
    return ctx.obj  # type: ignore[return-value]


def _run_service(service_call: Callable[[], None]) -> None:
    """Invoke a service and translate its outcome into CLI output.

    This is the only place command output formatting and exit-code
    mapping happen, keeping business logic out of the command functions
    themselves (NFR-X.2, FR-2.10).
    """
    try:
        service_call()
    except NotYetImplementedError as exc:
        typer.echo(f"'{exc}' is not yet implemented.")
    except SQLCoachError as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=_exit_code_for(exc)) from exc


def _render_analyze_result(result: AnalyzeResult) -> None:
    """Print an AnalyzeResult as a ranked recommendation report."""
    typer.echo(f"Parsed {result.queries_parsed} query(ies).")
    if result.analyzed_against_database:
        typer.echo(f"Analyzed {result.queries_analyzed} query(ies) against the database.")
    else:
        typer.echo(
            "Ran static checks only. Pass --db-url to also analyze execution plans "
            "and recommend indexes."
        )

    if not result.recommendations:
        typer.echo("No recommendations -- nothing was flagged.")
        return

    typer.echo(
        f"\n{len(result.recommendations)} recommendation(s), highest impact first:\n"
    )
    for index, rec in enumerate(result.recommendations, start=1):
        typer.echo(f"{index}. [{rec.confidence.value} confidence] {rec.problem}")
        typer.echo(f"   Root cause: {rec.root_cause}")
        typer.echo(f"   Why: {rec.technical_explanation}")
        typer.echo(f"   Fix: {rec.recommended_solution}")
        if rec.sql_example:
            typer.echo(f"   SQL: {rec.sql_example}")
        typer.echo(f"   Impact: {rec.expected_impact}")
        if rec.risks:
            typer.echo(f"   Risks: {'; '.join(rec.risks)}")
        typer.echo("")

def _render_diff_section(label: str, diff) -> None:  # type: ignore[no-untyped-def]
    typer.echo(f"{label}:")
    typer.echo(f"  Resolved ({len(diff.removed)}): {', '.join(diff.removed) or '(none)'}")
    typer.echo(f"  New ({len(diff.added)}): {', '.join(diff.added) or '(none)'}")
    typer.echo(
        f"  Still present ({len(diff.unchanged)}): "
        f"{', '.join(diff.unchanged) or '(none)'}"
    )


def _render_metric(
    label: str,
    before: Optional[float],
    after: Optional[float],
    *,
    unit: str = "",
    observed: bool = False,
) -> None:
    if before is None or after is None:
        return
    tag = "  (observed)" if observed else ""
    if before > 0:
        pct = (after - before) / before * 100
        typer.echo(f"  {label}: {before:.2f}{unit} -> {after:.2f}{unit} ({pct:+.1f}%){tag}")
    else:
        typer.echo(f"  {label}: {before:.2f}{unit} -> {after:.2f}{unit}{tag}")


def _render_comparison_result(result: ComparisonResult) -> None:
    """Print a ComparisonResult as a before/after diff with a verdict."""
    _render_diff_section("Anti-patterns", result.anti_patterns)

    if result.compared_against_database:
        _render_diff_section("Execution-plan issues", result.plan_findings)
        _render_diff_section("Index recommendations", result.index_recommendations)
        typer.echo("Execution plan:")
        if result.plan_shape_before and result.plan_shape_after:
            typer.echo(
                f"  Plan shape: {result.plan_shape_before} -> {result.plan_shape_after}"
            )
        _render_metric(
            "Estimated cost",
            result.estimated_cost_before,
            result.estimated_cost_after,
        )
        _render_metric(
            "Execution time",
            result.execution_time_ms_before,
            result.execution_time_ms_after,
            unit=" ms",
            observed=True,
        )
    else:
        typer.echo(
            "(static compare; pass --db-url to also diff plan shape, cost, and time)"
        )

    resolved = (
        len(result.anti_patterns.removed)
        + len(result.plan_findings.removed)
        + len(result.index_recommendations.removed)
    )
    introduced = (
        len(result.anti_patterns.added)
        + len(result.plan_findings.added)
        + len(result.index_recommendations.added)
    )
    if resolved and not introduced:
        verdict = "Improvement"
    elif introduced and not resolved:
        verdict = "Regression"
    elif introduced and resolved:
        verdict = "Mixed"
    else:
        verdict = "No change"
    typer.echo(
        f"\nVerdict: {verdict} -- {resolved} issue(s) resolved, {introduced} introduced."
    )

@app.command()
def analyze(
    ctx: typer.Context,
    source: Optional[Path] = typer.Argument(
        None, help="Path to a .sql file to analyze."
    ),
    db_url: Optional[str] = typer.Option(
        None,
        "--db-url",
        help=(
            "PostgreSQL connection string. When given, each parsed query is run "
            "through EXPLAIN ANALYZE and its execution plan inspected."
        ),
    ),
    confirm_mutations: bool = typer.Option(
        False,
        "--confirm-mutations",
        help=(
            "Allow EXPLAIN ANALYZE to run statements that modify data or take locks. "
            "Off by default; such statements are skipped unless this is set."
        ),
    ),
) -> None:
    """Analyze a SQL workload and report performance issues."""
    settings = _settings_from(ctx)

    def run() -> None:
        result = analyze_service(
            source,
            db_url=db_url,
            confirm_mutations=confirm_mutations,
            settings=settings,
        )
        _render_analyze_result(result)

    _run_service(run)


@app.command()
def audit(
    db_url: Optional[str] = typer.Option(
        None, "--db-url", help="PostgreSQL connection string. (Not yet implemented.)"
    ),
) -> None:
    """Run a full database health check (missing/duplicate/unused indexes, anti-patterns)."""
    _run_service(lambda: audit_service(db_url))


@app.command()
def report(
    output: Optional[Path] = typer.Argument(
        None, help="Path to write the generated report to. (Not yet implemented.)"
    ),
) -> None:
    """Generate a human-readable performance report."""
    _run_service(lambda: report_service(output))


@app.command()
def compare(
    ctx: typer.Context,
    before: Optional[Path] = typer.Argument(
        None, help="The 'before' .sql file (the original version)."
    ),
    after: Optional[Path] = typer.Argument(
        None, help="The 'after' .sql file (the optimized version)."
    ),
    db_url: Optional[str] = typer.Option(
        None,
        "--db-url",
        help="PostgreSQL connection string. When given, also diffs plan "
        "shape, estimated cost, and execution time.",
    ),
    confirm_mutations: bool = typer.Option(
        False,
        "--confirm-mutations",
        help="Allow EXPLAIN ANALYZE to run statements that modify data or take locks.",
    ),
) -> None:
    """Compare performance characteristics between two versions of a query."""
    settings = _settings_from(ctx)

    def run() -> None:
        result = compare_service(
            before,
            after,
            db_url=db_url,
            confirm_mutations=confirm_mutations,
            settings=settings,
        )
        _render_comparison_result(result)

    _run_service(run)