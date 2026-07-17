#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
mkdir -p .streamlit data
if [[ ! -f .streamlit/secrets.toml ]]; then
  cp .streamlit/secrets.example.toml .streamlit/secrets.toml
  echo "Created .streamlit/secrets.toml. Open it and add your Google Books key and email."
fi
echo "Setup complete. Run: ./scripts/run_mac.sh"
