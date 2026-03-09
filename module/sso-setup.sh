#!/bin/bash
# Ancroo SSO Setup — Creates Keycloak OAuth2 client for Ancroo
# Called by sso-hook.sh when ancroo-backend module is registered with SSO.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

source "$PROJECT_ROOT/tools/install/lib/common.sh"

set -a
source "$PROJECT_ROOT/.env"
set +a

print_info "Erstelle Keycloak-Client fuer Ancroo..."

# Ancroo uses a public client (PKCE flow) — browser extension cannot store secrets
python3 "$PROJECT_ROOT/modules/sso/keycloak-client-manager.py" \
    register \
    --admin-user "${KEYCLOAK_ADMIN:-admin}" \
    --admin-password "$KEYCLOAK_ADMIN_PASSWORD" \
    --keycloak-url "http://localhost:8080" \
    --realm "${KEYCLOAK_REALM:-ancroo}" \
    --client-id "ancroo" \
    --display-name "Ancroo AI Workflows" \
    --redirect-uri "https://${ANCROO_DOMAIN:-ancroo.${BASE_DOMAIN}}/callback" \
    --sso-group "standard-users" \
    --public-client

# Add chrome extension redirect URI for PKCE login via chrome.identity
# The wildcard covers any extension ID (development + production)
KEYCLOAK_URL="http://localhost:8080"
REALM="${KEYCLOAK_REALM:-ancroo}"
ANCROO_REDIRECT="https://${ANCROO_DOMAIN:-ancroo.${BASE_DOMAIN}}/callback"

ADMIN_TOKEN=$(curl -sf "${KEYCLOAK_URL}/realms/master/protocol/openid-connect/token" \
    -d "grant_type=password" \
    -d "client_id=admin-cli" \
    -d "username=${KEYCLOAK_ADMIN:-admin}" \
    -d "password=${KEYCLOAK_ADMIN_PASSWORD}" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

CLIENT_UUID=$(curl -sf "${KEYCLOAK_URL}/admin/realms/${REALM}/clients?clientId=ancroo" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")

curl -sf "${KEYCLOAK_URL}/admin/realms/${REALM}/clients/${CLIENT_UUID}" \
    -X PUT \
    -H "Authorization: Bearer ${ADMIN_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "$(python3 -c "
import json, sys
data = json.loads(sys.stdin.read())
uris = set(data.get('redirectUris', []))
uris.add('${ANCROO_REDIRECT}')
uris.add('${ANCROO_REDIRECT}/*')
uris.add('https://*.chromiumapp.org/*')
data['redirectUris'] = sorted(uris)
json.dump(data, sys.stdout)
" < <(curl -sf "${KEYCLOAK_URL}/admin/realms/${REALM}/clients/${CLIENT_UUID}" \
    -H "Authorization: Bearer ${ADMIN_TOKEN}"))"

print_success "Ancroo Keycloak-Client erstellt (Public Client, PKCE + Extension redirect)"
