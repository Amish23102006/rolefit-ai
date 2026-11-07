#!/usr/bin/env bash
# Start the API (port 8000) and the Streamlit UI (port 8501) together. Ctrl+C stops both.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ] || [ ! -f .env ]; then
  ./scripts/setup.sh
fi
# shellcheck disable=SC1091
source .venv/bin/activate
API_PORT="${API_PORT:-8000}"
UI_PORT="${UI_PORT:-8501}"
export API_URL="${API_URL:-http://127.0.0.1:${API_PORT}}"

python -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" &
API_PID=$!
trap 'kill $API_PID 2>/dev/null || true' EXIT INT TERM

for _ in $(seq 1 40); do
  if python -c "import httpx,sys; sys.exit(0 if httpx.get('${API_URL}/healthz', timeout=1).status_code == 200 else 1)" 2>/dev/null; then
    break
  fi
  sleep 0.25
done
echo "API:  ${API_URL}/docs"
echo "UI:   http://127.0.0.1:${UI_PORT}"
python -m streamlit run ui/app.py --server.port "$UI_PORT" --server.address 127.0.0.1 --browser.gatherUsageStats false
