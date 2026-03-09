#!/bin/bash
# install-stack.sh — Install Ancroo Backend as an Ancroo Stack module
#
# Usage:
#   ./install-stack.sh /path/to/ancroo-stack
#
# This symlinks the module files into the target stack's modules/ancroo-backend/
# directory, then enables the module. The Docker image is pulled from ghcr.io.
#
# To uninstall, run from the Ancroo Stack directory:
#   ./module.sh disable ancroo-backend && rm modules/ancroo-backend
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_NAME="ancroo-backend"

# ─── Validate arguments ──────────────────────────────────────
if [[ $# -lt 1 ]]; then
    echo "Usage: $0 /path/to/ancroo-stack"
    echo ""
    echo "Installs Ancroo Backend as a module into an existing Ancroo Stack."
    exit 1
fi

STACK_DIR="$(cd "$1" 2>/dev/null && pwd)" || {
    echo "Error: Directory '$1' does not exist."
    exit 1
}

if [[ ! -f "$STACK_DIR/module.sh" ]]; then
    echo "Error: '$STACK_DIR' does not look like an Ancroo Stack installation."
    echo "       Expected to find module.sh in that directory."
    exit 1
fi

TARGET_DIR="$STACK_DIR/modules/$MODULE_NAME"

# ─── Check for existing installation ─────────────────────────
if [[ -L "$TARGET_DIR" || -d "$TARGET_DIR" ]]; then
    echo "Ancroo module already installed at $TARGET_DIR"
    if [[ "${ANCROO_INSTALL_OVERWRITE:-n}" == "y" ]]; then
        echo "Overwriting existing installation (ANCROO_INSTALL_OVERWRITE=y)"
    else
        read -r -p "Overwrite? [y/N] " confirm
        if [[ "$confirm" != [yY] ]]; then
            echo "Aborted."
            exit 0
        fi
    fi
    # Remove safely: if TARGET_DIR is a symlink, rm -rf would follow it
    # and delete files in the source repo. Use rm -f for symlinks instead.
    if [[ -L "$TARGET_DIR" ]]; then
        rm -f "$TARGET_DIR"
    else
        rm -rf "$TARGET_DIR"
    fi
fi

# ─── Symlink module directory ─────────────────────────────────
echo "Installing Ancroo module into $TARGET_DIR ..."
ln -sf "../../$(basename "$SCRIPT_DIR")/module" "$TARGET_DIR"
echo "Module directory linked."

# ─── Enable module ────────────────────────────────────────────
echo ""
if [[ -n "${ANCROO_ENABLE_NOW:-}" ]]; then
    if [[ "$ANCROO_ENABLE_NOW" == "y" ]]; then
        cd "$STACK_DIR"
        bash ./module.sh enable "$MODULE_NAME"
    else
        echo "Module files installed. To enable later, run:"
        echo "  cd $STACK_DIR && ./module.sh enable $MODULE_NAME"
    fi
else
    read -r -p "Enable module now? (runs ./module.sh enable ancroo-backend) [Y/n] " enable
    if [[ "$enable" != [nN] ]]; then
        cd "$STACK_DIR"
        bash ./module.sh enable "$MODULE_NAME"
    else
        echo ""
        echo "Module files installed. To enable later, run:"
        echo "  cd $STACK_DIR && ./module.sh enable $MODULE_NAME"
    fi
fi
