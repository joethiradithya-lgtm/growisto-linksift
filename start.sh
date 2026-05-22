#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────
# LinkSift Agent — one-click startup (macOS / Linux)
# ────────────────────────────────────────────────────────────
# Double-click this file (or run `bash start.sh` in terminal).
# It will:
#   1. Check Python 3.10+ and Node.js are installed
#   2. Create a virtualenv and install dependencies
#   3. Start the server and open the browser

set -e
cd "$(dirname "$0")"

echo ""
echo "╔════════════════════════════════════════════╗"
echo "║   LinkSift Agent — Startup                 ║"
echo "╚════════════════════════════════════════════╝"
echo ""

# ── 1. Check Python ─────────────────────────────────────────
echo "→ Checking Python..."
if ! command -v python3 &> /dev/null; then
    echo "✗ Python 3 is not installed."
    echo "  Install from https://www.python.org/downloads/ (need 3.10+)"
    read -p "Press Enter to exit..."
    exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]); then
    echo "✗ Python $PY_VERSION found, but we need 3.10 or higher."
    echo "  Install a newer Python from https://www.python.org/downloads/"
    read -p "Press Enter to exit..."
    exit 1
fi
echo "  ✓ Python $PY_VERSION"

# ── 2. Check Node.js (required by Claude Agent SDK's bundled CLI) ─
echo "→ Checking Node.js..."
if ! command -v node &> /dev/null; then
    echo "✗ Node.js is not installed."
    echo "  The Claude Agent SDK needs Node.js to run its bundled CLI."
    echo "  Install from https://nodejs.org/ (LTS version is fine)"
    read -p "Press Enter to exit..."
    exit 1
fi
NODE_VERSION=$(node --version)
echo "  ✓ Node.js $NODE_VERSION"

# ── 3. Set up virtualenv ────────────────────────────────────
cd backend
if [ ! -d ".venv" ]; then
    echo "→ Creating virtual environment..."
    python3 -m venv .venv
    echo "  ✓ Created .venv/"
fi

echo "→ Activating virtualenv & installing dependencies..."
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo "  ✓ Dependencies installed"

# ── 4. Start server ─────────────────────────────────────────
echo ""
echo "╔════════════════════════════════════════════╗"
echo "║   Server starting at:                      ║"
echo "║   → http://localhost:8000                  ║"
echo "║                                            ║"
echo "║   Press Ctrl+C to stop                     ║"
echo "╚════════════════════════════════════════════╝"
echo ""

# Open browser after a short delay (in background)
(sleep 2 && (
    if command -v open &> /dev/null; then
        open http://localhost:8000        # macOS
    elif command -v xdg-open &> /dev/null; then
        xdg-open http://localhost:8000    # Linux
    fi
)) &

# Run the server (this blocks until Ctrl+C)
uvicorn server:app --host 0.0.0.0 --port 8000
