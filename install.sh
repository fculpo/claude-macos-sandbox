#!/usr/bin/env bash
set -euo pipefail

PREFIX="${PREFIX:-${HOME}/.local/bin}"
CONFIG_DIR="${HOME}/.config/claude-sandbox"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$PREFIX"

cp "$SCRIPT_DIR/claude-sandbox" "$PREFIX/claude-sandbox"
cp "$SCRIPT_DIR/claude-sandbox-proxy.py" "$PREFIX/claude-sandbox-proxy.py"
chmod +x "$PREFIX/claude-sandbox" "$PREFIX/claude-sandbox-proxy.py"

echo "Installed to $PREFIX/claude-sandbox"

if [[ ! -f "$CONFIG_DIR/config" ]]; then
    mkdir -p "$CONFIG_DIR"
    cp "$SCRIPT_DIR/config.example" "$CONFIG_DIR/config"
    echo "Created default config at $CONFIG_DIR/config"
else
    echo "Config already exists at $CONFIG_DIR/config (not overwritten)"
fi
