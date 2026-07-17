#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -d .venv ]]; then
  echo "Virtual environment not found. Run ./scripts/setup_mac.sh first."
  exit 1
fi
source .venv/bin/activate
streamlit run app.py
