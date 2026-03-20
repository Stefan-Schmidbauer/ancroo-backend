#!/bin/bash
# install-stack.sh — Install Ancroo Backend into an Ancroo Stack
#
# Usage:
#   ./install-stack.sh /path/to/ancroo-stack
#
# This symlinks the module files into the target stack's modules/ancroo-backend/
# directory, adds compose files to COMPOSE_FILE, runs setup, and starts the service.
#
# To uninstall:
#   Remove compose entries from COMPOSE_FILE in .env, then:
#   docker compose stop ancroo-backend && rm modules/ancroo-backend
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODULE_NAME="ancroo-backend"

# ─── Validate arguments ──────────────────────────────────────
if [[ $# -lt 1 ]]; then
    echo "Usage: $0 /path/to/ancroo-stack"
    echo ""
    echo "Installs Ancroo Backend into an existing Ancroo Stack."
    exit 1
fi

STACK_DIR="$(cd "$1" 2>/dev/null && pwd)" || {
    echo "Error: Directory '$1' does not exist."
    exit 1
}

if [[ ! -f "$STACK_DIR/stack.sh" ]] && [[ ! -f "$STACK_DIR/module.sh" ]]; then
    echo "Error: '$STACK_DIR' does not look like an Ancroo Stack installation."
    echo "       Expected to find stack.sh in that directory."
    exit 1
fi

ENV_FILE="$STACK_DIR/.env"
TARGET_DIR="$STACK_DIR/modules/$MODULE_NAME"

# Load common functions if available
if [[ -f "$STACK_DIR/tools/install/lib/common.sh" ]]; then
    source "$STACK_DIR/tools/install/lib/common.sh"
else
    print_info()    { echo "  → $1"; }
    print_success() { echo "  ✓ $1"; }
    print_warning() { echo "  ⚠ $1"; }
    print_step()    { echo "  ▸ $1"; }
fi

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
    if [[ -L "$TARGET_DIR" ]]; then
        rm -f "$TARGET_DIR"
    else
        rm -rf "$TARGET_DIR"
    fi
fi

# ─── Symlink module directory ─────────────────────────────────
print_step "Installing Ancroo module into $TARGET_DIR"
mkdir -p "$STACK_DIR/modules"
ln -sf "../../$(basename "$SCRIPT_DIR")/module" "$TARGET_DIR"
print_success "Module directory linked"

# ─── Add compose files to COMPOSE_FILE ────────────────────────
add_compose_entry() {
    local entry="$1"
    local current
    current=$(grep '^COMPOSE_FILE=' "$ENV_FILE" 2>/dev/null | sed 's/^COMPOSE_FILE=//;s/^"//;s/"$//')
    if [[ ":$current:" != *":$entry:"* ]]; then
        local new_val="${current}:${entry}"
        # Atomic update
        local tmp
        tmp=$(mktemp)
        while IFS= read -r line; do
            if [[ "$line" =~ ^COMPOSE_FILE= ]]; then
                echo "COMPOSE_FILE=\"${new_val}\"" >> "$tmp"
            else
                echo "$line" >> "$tmp"
            fi
        done < "$ENV_FILE"
        mv -f "$tmp" "$ENV_FILE"
    fi
}

if [[ -n "${ANCROO_ENABLE_NOW:-}" ]] && [[ "$ANCROO_ENABLE_NOW" == "y" ]]; then
    ENABLE_NOW=true
elif [[ -n "${ANCROO_ENABLE_NOW:-}" ]]; then
    ENABLE_NOW=false
else
    ENABLE_NOW=true
    read -r -p "Enable and start now? [Y/n] " enable
    [[ "$enable" == [nN] ]] && ENABLE_NOW=false
fi

if $ENABLE_NOW; then
    print_step "Adding compose files to COMPOSE_FILE"
    add_compose_entry "../ancroo-backend/module/compose.yml"
    add_compose_entry "../ancroo-backend/module/compose.ports.yml"

    # Run setup script (generates secrets, configures env vars)
    if [[ -f "$TARGET_DIR/setup.sh" ]]; then
        print_step "Running setup..."
        source "$TARGET_DIR/setup.sh"
    fi

    # Create database
    print_step "Ensuring database exists..."
    if docker exec postgres psql -U "${POSTGRES_USER:-ancroo}" -lqt 2>/dev/null | grep -qw "ancroo"; then
        print_info "Database 'ancroo' already exists"
    else
        docker exec postgres psql -U "${POSTGRES_USER:-ancroo}" -c "CREATE DATABASE ancroo;" 2>/dev/null || true
        print_success "Database 'ancroo' created"
    fi

    # Add homepage dashboard entry
    homepage_snippet="$TARGET_DIR/homepage.yml"
    homepage_services="$STACK_DIR/data/homepage/services.yaml"
    if [[ -f "$homepage_snippet" ]] && [[ -f "$homepage_services" ]]; then
        if ! grep -q "ancroo-backend" "$homepage_services" 2>/dev/null; then
            # Set defaults for envsubst
            export ANCROO_PORT="${ANCROO_PORT:-8900}"
            export HOST_IP
            HOST_IP=$(grep '^HOST_IP=' "$ENV_FILE" 2>/dev/null | sed 's/^[^=]*=//;s/^"//;s/"$//' || echo "localhost")
            echo "" >> "$homepage_services"
            grep -v '^#' "$homepage_snippet" | envsubst >> "$homepage_services"
            print_success "Homepage dashboard updated"
        fi
    fi

    # Start service
    print_step "Starting ancroo-backend..."
    cd "$STACK_DIR"
    docker compose up -d ancroo-backend
    print_success "Ancroo Backend started"
else
    echo ""
    echo "Module files installed. To enable later:"
    echo "  1. Add compose entries to COMPOSE_FILE in .env"
    echo "  2. Run: cd $STACK_DIR && docker compose up -d ancroo-backend"
fi
