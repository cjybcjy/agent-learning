import subprocess
import sys


def test_cli_scan_command_exists():
    result = subprocess.run(
        [sys.executable, "-m", "main", "scan", "--help"],
        capture_output=True,
        text=True,
        cwd="/home/kyrie/workspace/agent-learning",
    )
    assert result.returncode == 0
    assert "theme" in result.stdout.lower()
