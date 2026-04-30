"""Helpers to run lark-cli commands as subprocess."""

from __future__ import annotations

import json
import logging
import subprocess

logger = logging.getLogger(__name__)


class LarkCliError(Exception):
    """Raised when lark-cli exits non-zero or returns an error payload."""


def run_lark_cli(args: list[str], *, timeout: int = 30) -> dict:
    """Execute a lark-cli command and return parsed JSON output.

    Raises LarkCliError on failure.
    """
    cmd = ["lark-cli", *args, "--output", "json"]
    logger.debug("lark-cli command: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise LarkCliError(f"lark-cli timed out after {timeout}s") from exc
    except FileNotFoundError as exc:
        raise LarkCliError("lark-cli not found in PATH") from exc

    if result.returncode != 0:
        raise LarkCliError(f"lark-cli exited {result.returncode}: {result.stderr.strip()}")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        # Some commands output non-JSON; return raw stdout in a dict
        return {"raw": result.stdout.strip()}
