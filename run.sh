#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CONFIG_FILE="$SCRIPT_DIR/config.yaml"
VENV_DIR="$SCRIPT_DIR/.venv"
PORT="${PORT:-8010}"

# ── Kill existing instance on this port ───────────────────────

OLD_PID=$(ss -tlnp "sport = :$PORT" 2>/dev/null | grep -oP 'pid=\K\d+' || true)
if [ -n "$OLD_PID" ]; then
    echo "→ Killing old server on port $PORT (PID $OLD_PID)..."
    kill "$OLD_PID" 2>/dev/null || true
    sleep 1
fi

# ── First-time / update setup ─────────────────────────────────

if [ ! -d "$VENV_DIR" ]; then
    echo "→ Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Reinstall if requirements.txt is newer than the venv marker
MARKER="$VENV_DIR/.requirements_hash"
NEED_INSTALL=0
if [ ! -f "$VENV_DIR/bin/python" ]; then
    NEED_INSTALL=1
elif [ ! -f "$MARKER" ] || [ requirements.txt -nt "$MARKER" ]; then
    NEED_INSTALL=1
fi
if [ "$NEED_INSTALL" -eq 1 ]; then
    echo "→ Installing/updating dependencies..."
    "$VENV_DIR/bin/pip" install -q -r requirements.txt
    touch "$MARKER"
fi

if [ ! -f "$CONFIG_FILE" ]; then
    echo "→ First run — configure API credentials"
    echo "  Get your user_id and api_key from:"
    echo "  https://rule34.xxx/index.php?page=account&s=options"
    echo ""
    read -rp "  user_id: " USER_ID
    read -rp "  api_key: " API_KEY

    mkdir -p "$SCRIPT_DIR"
    cat > "$CONFIG_FILE" << YAMLEOF
credentials: "&api_key=${API_KEY}&user_id=${USER_ID}"
delay: 1.0
download_dir: "./downloads"
timeout: 30
YAMLEOF
    echo "→ Config saved to $CONFIG_FILE"
fi

# ── Run ────────────────────────────────────────────────────────

echo ""
"$VENV_DIR/bin/python" server.py
