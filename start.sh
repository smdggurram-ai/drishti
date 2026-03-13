#!/usr/bin/env bash
# start.sh — launch NeuralTest backend + frontend

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

# ── 1. Check ANTHROPIC_API_KEY ────────────────────────────────────────────────
if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "⚠  ANTHROPIC_API_KEY is not set."
  echo "   Export it before running: export ANTHROPIC_API_KEY=sk-ant-..."
  exit 1
fi

# ── 2. Python deps ────────────────────────────────────────────────────────────
echo "📦 Installing Python dependencies..."
cd "$ROOT"
pip install -r requirements.txt -q
playwright install chromium --with-deps -q

# ── 3. Node deps ──────────────────────────────────────────────────────────────
echo "📦 Installing Node dependencies..."
cd "$ROOT/frontend"
npm install -q

# ── 4. Launch ─────────────────────────────────────────────────────────────────
echo ""
echo "🚀 Starting NeuralTest..."
echo "   Backend  → http://localhost:8000"
echo "   Frontend → http://localhost:5173"
echo "   API docs → http://localhost:8000/docs"
echo ""

# Start FastAPI in background
cd "$ROOT/backend"
uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!

# Start Vite dev server in foreground
cd "$ROOT/frontend"
npm run dev

# Kill backend when frontend exits
kill $BACKEND_PID 2>/dev/null || true
