#!/bin/bash
# install-stack.sh — Install Ancroo as an Ancroo Stack module
#
# Usage:
#   ./install-stack.sh /path/to/ancroo-stack
#
# This copies the module files into the target stack's modules/ancroo/
# directory, then enables the module. The Docker image is pulled from ghcr.io.
#
# To uninstall, run from the Ancroo Stack directory:
#   ./module.sh disable ancroo && rm -rf modules/ancroo/
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_NAME="ancroo"

# ─── Validate arguments ──────────────────────────────────────
if [[ $# -lt 1 ]]; then
    echo "Usage: $0 /path/to/ancroo-stack"
    echo ""
    echo "Installs Ancroo as a module into an existing Ancroo Stack."
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
if [[ -L "$TARGET_DIR" ]]; then
    echo "Error: '$TARGET_DIR' is a symlink (development setup)."
    echo "       Remove it first: rm $TARGET_DIR"
    exit 1
fi

if [[ -d "$TARGET_DIR" ]]; then
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
    rm -rf "$TARGET_DIR"
fi

# ─── Copy module files ───────────────────────────────────────
MODULE_FILES=(
    module.conf
    module.env
    compose.yml
    compose.ports.yml
    compose.traefik.yml
    compose.sso.yml
    setup.sh
    sso-setup.sh
    homepage.yml
    homepage.ssl.yml
)

echo "Installing Ancroo module into $TARGET_DIR ..."
mkdir -p "$TARGET_DIR"

for file in "${MODULE_FILES[@]}"; do
    if [[ -f "$SCRIPT_DIR/module/$file" ]]; then
        cp "$SCRIPT_DIR/module/$file" "$TARGET_DIR/$file"
    fi
done

# Dev mode: generate compose.build.yml pointing to local source
if [[ "${ANCROO_LOCAL_BUILD:-}" == "y" ]]; then
    BACKEND_REL_PATH="../$(basename "$SCRIPT_DIR")"
    cat > "$TARGET_DIR/compose.build.yml" <<BUILDEOF
# Auto-generated for local development builds
services:
  ancroo-backend:
    image: ghcr.io/stefan-schmidbauer/ancroo-backend:latest
    build:
      context: ${BACKEND_REL_PATH}
      dockerfile: Dockerfile
      args:
        BUILD_COMMIT: \${BUILD_COMMIT:-dev}
        BUILD_VERSION: \${BUILD_VERSION:-dev}
BUILDEOF
    echo "Dev mode: compose.build.yml generated (context: $BACKEND_REL_PATH)"
fi

echo "Module files copied."

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
    read -r -p "Enable module now? (runs ./module.sh enable ancroo) [Y/n] " enable
    if [[ "$enable" != [nN] ]]; then
        cd "$STACK_DIR"
        bash ./module.sh enable "$MODULE_NAME"
    else
        echo ""
        echo "Module files installed. To enable later, run:"
        echo "  cd $STACK_DIR && ./module.sh enable $MODULE_NAME"
    fi
fi
