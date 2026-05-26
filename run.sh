#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CONFIG_FILE="$HOME/.config/rule34-tool/config.yaml"
VENV_DIR="$SCRIPT_DIR/.venv"
PORT="${PORT:-8010}"

# ── First-time setup ──────────────────────────────────────────

if [ ! -d "$VENV_DIR" ]; then
    echo "→ Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

if ! "$VENV_DIR/bin/python" -c "import flask" 2>/dev/null; then
    echo "→ Installing dependencies..."
    "$VENV_DIR/bin/pip" install -q flask requests tqdm pyyaml
fi

if [ ! -f "$CONFIG_FILE" ]; then
    echo "→ First run — configure API credentials"
    echo "  Get your user_id and api_key from:"
    echo "  https://rule34.xxx/index.php?page=account&s=options"
    echo ""
    read -rp "  user_id: " USER_ID
    read -rp "  api_key: " API_KEY

    mkdir -p "$(dirname "$CONFIG_FILE")"
    cat > "$CONFIG_FILE" << YAMLEOF
user_id: "$USER_ID"
api_key: "$API_KEY"
delay: 1.0
download_dir: "./downloads"
timeout: 30
YAMLEOF
    echo "→ Config saved to $CONFIG_FILE"
fi

# ── Run ────────────────────────────────────────────────────────

echo ""
echo "╔══════════════════════════════════════╗"
echo "║       Rule34 Tool — Web UI          ║"
echo "╠══════════════════════════════════════╣"
echo "║  Open     → http://localhost:${PORT}       ║"
echo "╚══════════════════════════════════════╝"
echo ""

exec "$VENV_DIR/bin/python" server.py
