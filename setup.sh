#!/bin/bash
# One-shot setup: venv + deps. Safe to re-run.
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
echo "Setup complete. Start the API with:"
echo "  .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
