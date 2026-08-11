"""SQLCoach CLI entry point.

This module owns only argument parsing, input validation, invoking
application services (none exist yet -- from Phase 2 onward), and
output formatting (NFR-X.2). Business logic must never live here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from sqlcoach.config import load_settings
from sqlcoach.exceptions import SQLCoachError
from sqlcoach.logging_config import configure_logging
from sqlcoach.reports.services import (
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


@app.callback()
def main(
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
    """Load settings and configure logging before any subcommand runs."""
    try:
        settings = load_settings(config_file)
    except SQLCoachError as exc:
        typer.secho(f"Configuration error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    # A --json-logs flag on the command line always wins over config/env,
    # since it represents the most specific, most recently expressed intent.
    configure_logging(level=settings.log_level, json_output=json_logs or settings.json_logs)

def _run_service(service_call: Callable[[], None]) -> None:
    """Invoke a service and translate a not-yet-implemented signal into
    the CLI's standard user-facing message.

    Every command function below reduces to exactly one call to this
    helper -- this is the only place command output formatting happens,
    keeping business logic (even placeholder business logic) entirely
    out of the command functions themselves (NFR-X.2, FR-2.10).
    """
    try:
        service_call()
    except NotYetImplementedError as exc:
        typer.echo(f"'{exc}' is not yet implemented.")



@app.command()
def analyze(
    source: Optional[Path] = typer.Argument(
        None, help="SQL file, log file, or source to analyze. (Not yet implemented.)"
    ),
) -> None:
    """Analyze a SQL workload and report performance issues."""
    _run_service(lambda: analyze_service(source))


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