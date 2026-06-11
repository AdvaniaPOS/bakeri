from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_database_module_fails_fast_without_database_url_in_production():
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["APP_ENV"] = "production"
    env["DATABASE_URL"] = ""
    env["PYTHONPATH"] = str(repo_root)

    result = subprocess.run(
        [sys.executable, "-c", "import app.database"],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    combined_output = f"{result.stdout}\n{result.stderr}"
    assert "DATABASE_URL environment variable is required in production-like environments" in combined_output