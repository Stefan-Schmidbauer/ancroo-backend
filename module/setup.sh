#!/bin/bash
# Ancroo Module Setup — Secret key generation & n8n API key
#
# Generates ANCROO_SECRET_KEY automatically if not yet configured,
# then configures the n8n API key for workflow integration.
#
# This script can be re-run at any time via:
#   ./module.sh setup ancroo
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env"

source "$PROJECT_ROOT/tools/install/lib/common.sh" 2>/dev/null || {
    print_info() { echo "  → $1"; }
    print_success() { echo "  ✓ $1"; }
    print_warning() { echo "  ⚠ $1"; }
    print_step() { echo "  ▸ $1"; }
}

# Read current value of an env var from .env
get_env_value() {
    local key="$1"
    grep "^${key}=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"' || echo ""
}

# Set or update an env var in .env (double-quoted for Docker Compose compatibility)
set_env_value() {
    local key="$1"
    local value="$2"
    local entry="${key}=\"${value}\""

    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
        # Remove old line and append new one (avoids sed delimiter issues)
        grep -v "^${key}=" "$ENV_FILE" > "${ENV_FILE}.tmp"
        echo "$entry" >> "${ENV_FILE}.tmp"
        mv "${ENV_FILE}.tmp" "$ENV_FILE"
    else
        echo "$entry" >> "$ENV_FILE"
    fi
}

# Generate secret only if it contains a CHANGE_ME placeholder or is empty
update_if_placeholder() {
    local key="$1"
    local generator="$2"

    local current_value
    current_value=$(get_env_value "$key")

    if [[ "$current_value" == CHANGE_ME* ]] || [[ -z "$current_value" ]]; then
        local new_value
        new_value=$($generator)
        set_env_value "$key" "$new_value"
        print_info "${key} generated"
    fi
}

# --- Secret Key ---

generate_secret_key() {
    openssl rand -hex 32
}

print_step "Checking Ancroo secret key..."
update_if_placeholder "ANCROO_SECRET_KEY" generate_secret_key
print_success "Secret key configured"

# --- Ollama Default Model ---

if [[ -n "${ANCROO_OLLAMA_MODEL_INPUT:-}" ]]; then
    set_env_value "ANCROO_OLLAMA_MODEL" "$ANCROO_OLLAMA_MODEL_INPUT"
    print_info "Ollama default model: $ANCROO_OLLAMA_MODEL_INPUT"
fi

# --- Workflow Backends ---

if [[ -n "${ANCROO_BACKENDS_INPUT:-}" ]]; then
    set_env_value "ANCROO_BACKENDS" "$ANCROO_BACKENDS_INPUT"
    print_info "Workflow backends: $ANCROO_BACKENDS_INPUT"
fi

# --- Whisper-ROCm Auto-Detection ---
# When the whisper-rocm module is enabled, automatically set the ROCm STT URL
# so the ancroo-backend container can discover and prefer the GPU provider.

enabled_modules_for_rocm=$(get_env_value "ENABLED_MODULES")
current_rocm_url=$(get_env_value "ANCROO_WHISPER_ROCM_URL")

if echo "$enabled_modules_for_rocm" | grep -qw "whisper-rocm"; then
    if [[ -z "$current_rocm_url" ]]; then
        set_env_value "ANCROO_WHISPER_ROCM_URL" "http://whisper-rocm:8000"
        print_success "Whisper-ROCm detected — ANCROO_WHISPER_ROCM_URL set automatically"
    fi
else
    if [[ -n "$current_rocm_url" ]]; then
        set_env_value "ANCROO_WHISPER_ROCM_URL" ""
        print_info "Whisper-ROCm not enabled — cleared ANCROO_WHISPER_ROCM_URL"
    fi
fi

# --- n8n API Key ---
# The n8n post-enable.sh auto-provisions an owner account and API key,
# storing it as ANCROO_N8N_API_KEY in .env.  We only need to check here.

# Support non-interactive mode via env vars (used by ancroo/install.sh)
if [[ -n "${ANCROO_N8N_API_KEY_INPUT:-}" ]]; then
    set_env_value "ANCROO_N8N_API_KEY" "$ANCROO_N8N_API_KEY_INPUT"
    print_success "n8n API key configured (non-interactive)"
else
    current_key=$(get_env_value "ANCROO_N8N_API_KEY")

    if [[ -n "$current_key" ]] && [[ "$current_key" != CHANGE_ME* ]]; then
        print_success "n8n API key already configured"
    else
        print_warning "n8n API key not found"
        echo "  Enable the n8n module first (creates the key automatically),"
        echo "  then re-run: ./module.sh setup ancroo"
    fi
fi

