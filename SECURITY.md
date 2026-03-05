# Security Policy

For the overall Ancroo security policy, roadmap, and Phase 1 limitations, see the [central security policy](https://github.com/Stefan-Schmidbauer/ancroo/blob/main/SECURITY.md).

## Backend-Specific Notes

- **Authentication** is disabled by default (`AUTH_ENABLED=false`). When enabled, the backend uses OIDC/Keycloak via the SSO module.
- **CORS** is configured to allow Chrome extensions by default. Restrict `CORS_EXTENSION_IDS` in production.
- **API keys** for providers (Ollama, n8n) are encrypted at rest in the database using `SECRET_KEY`.
- **File uploads** are validated for size and type, then deleted after processing.
- **Internal URLs** (Ollama, Whisper, n8n) are not exposed in API responses.

## Reporting a Vulnerability

Please report security vulnerabilities through [GitHub's private vulnerability reporting](https://github.com/Stefan-Schmidbauer/ancroo-backend/security/advisories/new).

Do not open a public issue for security vulnerabilities.

You can expect an initial response within a few days. If the vulnerability is confirmed, a fix will be released as soon as possible.
