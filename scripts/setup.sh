#!/usr/bin/env bash
# One-time setup for macOS/Linux: virtualenv, dependencies and a safe .env.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
if [ ! -d .venv ]; then
  echo "Creating virtual environment (.venv)..."
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements-dev.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi
# Replace a missing or placeholder JWT secret with a strong random one (the value is never printed).
if ! grep -q '^ROLEFIT_JWT_SECRET=' .env || grep -q '^ROLEFIT_JWT_SECRET=change-me' .env || grep -q '^ROLEFIT_JWT_SECRET=$' .env; then
  SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
  python - "$SECRET" <<'PY'
import re, sys, pathlib
p = pathlib.Path(".env"); s = p.read_text()
line = "ROLEFIT_JWT_SECRET=" + sys.argv[1]
s = re.sub(r"^ROLEFIT_JWT_SECRET=.*$", line, s, flags=re.M) if re.search(r"^ROLEFIT_JWT_SECRET=", s, re.M) else line + "\n" + s
p.write_text(s)
PY
  echo "Generated a new ROLEFIT_JWT_SECRET in .env"
fi
# The old default Groq model was retired; move to the current default if it is still configured.
if grep -q '^ROLEFIT_LLM_MODEL=llama-3.3-70b-versatile' .env; then
  sed -i.bak 's#^ROLEFIT_LLM_MODEL=llama-3.3-70b-versatile#ROLEFIT_LLM_MODEL=openai/gpt-oss-120b#' .env && rm -f .env.bak
  echo "Updated retired ROLEFIT_LLM_MODEL to openai/gpt-oss-120b"
fi
chmod 600 .env
echo "Running tests..."
python -m pytest -q
echo
echo "Setup complete. Start everything with: ./run.sh"
