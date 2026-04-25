#!/usr/bin/env bash
set -euo pipefail

PREFIX="${PREFIX:-${HOME}/.local/bin}"
CONFIG_DIR="${HOME}/.config/claude-sandbox"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$PREFIX"

cp "$SCRIPT_DIR/claude-sandbox" "$PREFIX/claude-sandbox"
cp "$SCRIPT_DIR/codex-sandbox" "$PREFIX/codex-sandbox"
cp "$SCRIPT_DIR/claude-sandbox-proxy.py" "$PREFIX/claude-sandbox-proxy.py"
mkdir -p "$PREFIX/shims"
cp "$SCRIPT_DIR/shims/ps" "$PREFIX/shims/ps"
chmod +x "$PREFIX/claude-sandbox" "$PREFIX/codex-sandbox" "$PREFIX/claude-sandbox-proxy.py" "$PREFIX/shims/ps"

echo "Installed to $PREFIX/claude-sandbox"
echo "Installed to $PREFIX/codex-sandbox"

is_sandbox_alias() {
    local target="$1"
    local name="$2"
    [[ -f "$target" ]] && grep -q "# ${name}-sandbox alias shim" "$target"
}

install_alias() {
    local name="$1"
    local sandbox="$2"
    local env_var="$3"
    local active_var="$4"
    local target="$PREFIX/$name"
    local real="$PREFIX/$name.real"

    if [[ -e "$target" ]] && ! is_sandbox_alias "$target" "$name"; then
        if [[ -e "$real" ]]; then
            local backup="$target.pre-sandbox.$(date +%Y%m%d%H%M%S)"
            mv "$target" "$backup"
            echo "Preserved existing $target at $backup"
        else
            mv "$target" "$real"
            echo "Preserved existing $target at $real"
        fi
    fi

    cat > "$target" <<EOF
#!/usr/bin/env bash
# ${name}-sandbox alias shim
set -euo pipefail

PREFIX_DIR="$PREFIX"
REAL_BIN="$real"

find_real() {
    local old_ifs="\$IFS"
    IFS=:
    for dir in \$PATH; do
        IFS="\$old_ifs"
        [[ -n "\$dir" ]] || continue
        [[ "\$(cd "\$dir" 2>/dev/null && pwd -P)" != "\$(cd "\$PREFIX_DIR" 2>/dev/null && pwd -P)" ]] || continue
        if [[ -x "\$dir/$name" ]]; then
            printf '%s\n' "\$dir/$name"
            return 0
        fi
        IFS=:
    done
    IFS="\$old_ifs"
    return 1
}

if [[ "\${$active_var:-}" == "1" ]]; then
    if [[ -x "\$REAL_BIN" ]]; then
        exec "\$REAL_BIN" "\$@"
    fi
    if resolved="\$(find_real)"; then
        exec "\$resolved" "\$@"
    fi
    echo "$name-sandbox: could not find real $name binary" >&2
    exit 127
fi

if [[ -x "\$REAL_BIN" ]]; then
    export $env_var="\$REAL_BIN"
fi

exec "$PREFIX/$sandbox" "\$@"
EOF
    chmod +x "$target"
    echo "Installed alias $target -> $sandbox"
}

install_alias "claude" "claude-sandbox" "CLAUDE_BIN" "CLAUDE_SANDBOX_ACTIVE"
install_alias "codex" "codex-sandbox" "CODEX_BIN" "CODEX_SANDBOX_ACTIVE"

if [[ ! -f "$CONFIG_DIR/config" ]]; then
    mkdir -p "$CONFIG_DIR"
    cp "$SCRIPT_DIR/config.example" "$CONFIG_DIR/config"
    echo "Created default config at $CONFIG_DIR/config"
else
    echo "Config already exists at $CONFIG_DIR/config (not overwritten)"
fi
