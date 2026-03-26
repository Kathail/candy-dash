#!/usr/bin/env python3
"""Entry point for the Candy Route Planner application."""

import os
from pathlib import Path

# Load .env file if present
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

from app import create_app

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    port = int(os.environ.get("FLASK_PORT", 5000))
    debug = os.environ.get("FLASK_ENV") == "development"
    app.run(host=host, port=port, debug=debug)
