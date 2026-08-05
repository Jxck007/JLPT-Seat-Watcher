#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${project_dir}"

python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/playwright install --with-deps chromium
if [[ ! -f .env ]]; then
    cp .env.example .env
    chmod 600 .env
fi

echo "Installation complete. Set NTFY_TOPIC in ${project_dir}/.env, then run python main.py."
