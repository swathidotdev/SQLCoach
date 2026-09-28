"""Doc-example verification (Sprint 13, NFR-6.1).

Extracts the `sqlcoach ...` examples from docs/cli.md and runs the
database-free ones through the real CLI. This guarantees the documented
examples actually work: a broken or drifted example fails the build.

Examples that need a live database (those with --db-url) are skipped
here -- the integration suite covers the real-DB paths.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sqlcoach.cli.main import app

runner = CliRunner()

_DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
_DOC_FILES = ("cli.md", "user_guide.md")
_FENCE = re.compile(r"```(?:bash|console)?\n(.*?)```", re.DOTALL)


def _extract_commands() -> list[list[str]]:
    """Return the args of every `sqlcoach ...` example across the docs."""
    commands: list[list[str]] = []
    for name in _DOC_FILES:
        doc = _DOCS_DIR / name
        if not doc.exists():
            continue
        for block in _FENCE.findall(doc.read_text(encoding="utf-8")):
            for line in block.splitlines():
                line = line.strip()
                if line.startswith("sqlcoach "):
                    commands.append(shlex.split(line)[1:])
    return commands


def _needs_database(args: list[str]) -> bool:
    return "--db-url" in args


_ALL_COMMANDS = _extract_commands()
_STATIC_COMMANDS = [a for a in _ALL_COMMANDS if not _needs_database(a)]

# Documented exit codes a successful example is allowed to return.
_SUCCESS_CODE = 0


def test_doc_contains_examples() -> None:
    # Guard against the extractor silently finding nothing (e.g. if the
    # doc's fenced-block style changes).
    assert len(_STATIC_COMMANDS) >= 3


@pytest.mark.parametrize(
    "args", _STATIC_COMMANDS, ids=[" ".join(a) for a in _STATIC_COMMANDS]
)
def test_documented_static_example_runs(
    args: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Create the fixture files the doc examples reference, in an isolated
    # working directory so the bare relative filenames resolve.
    (tmp_path / "queries.sql").write_text(
        "SELECT * FROM users WHERE email = 'a@b.com';\n"
        "SELECT id FROM orders WHERE user_id = 1;\n",
        encoding="utf-8",
    )
    (tmp_path / "before.sql").write_text(
        "SELECT * FROM users WHERE email = 'a@b.com';\n", encoding="utf-8"
    )
    (tmp_path / "after.sql").write_text(
        "SELECT id, email FROM users WHERE email = 'a@b.com';\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, args)

    # The example must run without an unhandled crash...
    assert result.exception is None or isinstance(result.exception, SystemExit), (
        f"example `sqlcoach {' '.join(args)}` crashed: {result.exception!r}"
    )
    # ...and succeed (documented runnable examples are success cases;
    # error cases live in the exit-code table, not as runnable examples).
    assert result.exit_code == _SUCCESS_CODE, (
        f"example `sqlcoach {' '.join(args)}` exited {result.exit_code}"
    )