"""Helpers for isolated file-backed SQLite tests."""

import os
from pathlib import Path
import subprocess
import sys


BACKEND_DIRECTORY = Path(__file__).resolve().parents[1]


def run_alembic(database_path: Path, *arguments: str) -> None:
    """Run Alembic against one explicit temporary database."""
    environment = os.environ.copy()
    environment["DATABASE_PATH"] = str(database_path)
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=BACKEND_DIRECTORY,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise AssertionError(
            f"Alembic {' '.join(arguments)} failed:\n{completed.stderr}"
        )


def upgrade_database(database_path: Path) -> None:
    run_alembic(database_path, "upgrade", "head")
