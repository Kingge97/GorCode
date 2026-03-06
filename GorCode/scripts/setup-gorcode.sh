#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LAUNCHER="$REPO_ROOT/run_gorcode.py"

if [[ ! -f "$LAUNCHER" ]]; then
  echo "Launcher not found: $LAUNCHER" >&2
  exit 1
fi

BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"

WRAPPER="$BIN_DIR/gorcode"
cat > "$WRAPPER" <<'EOF'
#!/usr/bin/env bash
python3 "__LAUNCHER__" "$@"
EOF

# Replace placeholder with actual path
if command -v sed >/dev/null 2>&1; then
  sed -i.bak "s|__LAUNCHER__|$LAUNCHER|g" "$WRAPPER" && rm -f "$WRAPPER.bak"
else
  # Fallback without sed -i
  tmp="$WRAPPER.tmp"
  awk -v p="$LAUNCHER" '{gsub(/__LAUNCHER__/, p)}1' "$WRAPPER" > "$tmp" && mv "$tmp" "$WRAPPER"
fi

chmod +x "$WRAPPER"

# Ensure PATH includes ~/.local/bin
SHELL_NAME="$(basename "${SHELL:-}" )"
PROFILE=""
if [[ "$SHELL_NAME" == "zsh" ]]; then
  PROFILE="$HOME/.zshrc"
elif [[ "$SHELL_NAME" == "bash" ]]; then
  if [[ -f "$HOME/.bashrc" ]]; then
    PROFILE="$HOME/.bashrc"
  else
    PROFILE="$HOME/.bash_profile"
  fi
fi

if [[ -n "$PROFILE" ]]; then
  if ! grep -q 'export PATH="$HOME/.local/bin:$PATH"' "$PROFILE" 2>/dev/null; then
    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$PROFILE"
    echo "Updated $PROFILE to include ~/.local/bin in PATH"
  else
    echo "PATH already configured in $PROFILE"
  fi
else
  echo "Could not detect shell profile. Ensure ~/.local/bin is in PATH."
fi

echo "Installed gorcode command. Open a new terminal and run: gorcode --help"
