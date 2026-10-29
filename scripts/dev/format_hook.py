"""Claude Code PostToolUse hook: ruff-format and fix-imports a Python file right after an edit,
so formatting never fails CI. Reads the hook's JSON on stdin; silent unless ruff fails."""

import json
import subprocess
import sys

path = json.load(sys.stdin).get("tool_input", {}).get("file_path", "")
if path.endswith(".py"):
    for args in (["check", "--fix", "--select", "I", "-q"], ["format", "-q"]):
        subprocess.run(["uv", "run", "ruff", *args, path], check=False, capture_output=True)
