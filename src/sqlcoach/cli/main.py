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
from sqlcoach.reports.services import (
    AnalyzeResult,
    NotYetImplementedError,
    analyze_service,
    audit_service,
    compare_service,
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
    """Print an AnalyzeResult in human-readable form."""
    typer.echo(f"Parsed {result.queries_parsed} query(ies).")

    if not result.analyzed_against_database:
        typer.echo(
            "No --db-url given, so no execution plans were analyzed. "
            "Pass --db-url to run EXPLAIN ANALYZE and detect plan-level issues."
        )
        return

    typer.echo(f"Analyzed {result.queries_analyzed} query(ies) against the database.")

    if not result.findings:
        typer.echo("No execution-plan issues detected.")
        return

    typer.echo(f"Found {len(result.findings)} issue(s):")
    for finding in result.findings:
        location = f" on {finding.relation_name}" if finding.relation_name else ""
        typer.echo(f"  [{finding.severity.value.upper()}] {finding.code}{location}")
        typer.echo(f"      {finding.summary}")


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
    before: Optional[Path] = typer.Argument(
        None, help="Query or file representing the 'before' version. (Not yet implemented.)"
    ),
    after: Optional[Path] = typer.Argument(
        None, help="Query or file representing the 'after' version. (Not yet implemented.)"
    ),
) -> None:
    """Compare performance characteristics between two versions of a query."""
    _run_service(lambda: compare_service(before, after))


if __name__ == "__main__":
    app()