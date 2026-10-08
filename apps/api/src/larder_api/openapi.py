"""Write the OpenAPI schema to disk; the web app generates its client types from it.

Usage: python -m larder_api.openapi [OUTPUT_PATH]
"""

import json
import sys
from pathlib import Path

from larder_api.main import app

DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "openapi.json"


def main() -> None:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUTPUT
    output.write_text(json.dumps(app.openapi(), indent=2) + "\n")
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
