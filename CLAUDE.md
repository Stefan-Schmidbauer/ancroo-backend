# ancroo-backend — AI Workflow Backend

**Language:** Python 3.11 (FastAPI)
**License:** AGPL-3.0
**Package manager:** pip (requirements.txt)

## Key Files

| File | Purpose |
|------|---------|
| `packages/backend/src/main.py` | FastAPI app factory (`create_app()`) |
| `packages/backend/src/config.py` | Pydantic Settings (env-driven config) |
| `packages/backend/src/api/v1/router.py` | API v1 route aggregation |
| `packages/backend/src/api/v1/execution.py` | Workflow execution endpoints |
| `packages/backend/src/api/v1/workflows.py` | Workflow listing/sync endpoints |
| `packages/backend/src/api/v1/auth.py` | OIDC/Keycloak auth endpoints |
| `packages/backend/src/api/v1/tools.py` | Tool/plugin management |
| `packages/backend/src/api/v1/transcribe.py` | Direct STT transcription |
| `packages/backend/src/admin/routes.py` | Admin GUI (Jinja2 + HTMX) |
| `packages/backend/src/db/models.py` | SQLAlchemy ORM models |
| `packages/backend/src/db/session.py` | Database session & init |
| `packages/backend/src/execution/dispatcher.py` | Routes to LLM/STT/Tool executor |
| `packages/backend/src/integrations/runner.py` | ancroo-runner plugin discovery |
| `packages/backend/src/integrations/llm.py` | LLM provider interface |
| `packages/backend/src/integrations/stt.py` | STT integration |
| `packages/backend/src/integrations/n8n.py` | n8n workflow automation |
| `packages/backend/alembic/` | Database migrations (Alembic) |
| `module/` | ancroo-stack integration (Compose overlays) |

## API Endpoints (prefix: `/api/v1`)

**Workflows:**
- `GET /workflows` — List all accessible workflows
- `GET /workflows/{slug}` — Workflow detail
- `GET /workflows/sync/check?since=` — Incremental sync
- `POST /workflows/{slug}/execute` — Execute with text input
- `POST /workflows/{slug}/execute-upload` — Execute with file upload
- `GET /workflows/hotkeys/settings` — User hotkey config
- `PUT /workflows/hotkeys/settings` — Update hotkey config

**Auth (optional, OIDC/Keycloak):**
- `GET /auth/status` — Auth enabled?
- `GET /auth/oidc-config` — OIDC config for browser extension
- `GET /auth/login` — OAuth2 PKCE login
- `POST /auth/callback` — Token exchange
- `POST /auth/refresh` — Refresh token
- `GET /auth/me` — Current user
- `POST /auth/logout` — Logout

**Tools:**
- `GET /admin/tools` — List tools
- `POST /admin/tools/discover-runner` — Auto-discover ancroo-runner plugins

**Other:**
- `POST /transcribe` — Direct audio transcription
- `GET /health` — Health check
- `GET /api/v1/about` — Version info
- `GET /admin/` — Admin dashboard (HTML)

## Workflow Execution Flow

1. Extension sends text/audio to `/execute` or `/execute-upload`
2. `dispatcher.py` routes to executor by workflow type:
   - `text_transformation` → `llm_executor.py` → Ollama
   - `speech_to_text` → `stt_executor.py` → Whisper/Speaches
   - `tool` → `tool_executor.py` → ancroo-runner or n8n
3. Result returned to extension

## Database

PostgreSQL 16 + pgvector (shared via ancroo-stack).
Models: User, LLMModel, STTModel, Tool, Category, Workflow, WorkflowPermission, ExecutionLog, UserHotkeySetting.
Migrations: Alembic, auto-run on startup.

## Cross-Repo Interfaces

**Consumed by ancroo-web-backend:**
- All `/api/v1/` endpoints (REST, fetch-based)
- CORS configured for `chrome-extension://`

**Consumed by ancroo-voice:**
- `POST /api/v1/transcribe` (audio → text)

**Calls ancroo-runner:**
- `GET {runner_url}/plugins` — Plugin discovery
- `GET {runner_url}/health` — Health check
- `POST {endpoint_url}` — Plugin execution

**Depends on ancroo-stack:**
- PostgreSQL, Ollama, Whisper/Speaches, n8n, Keycloak (optional)

## Development

```bash
cd packages/backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn src.main:app --reload --port 8000
```

## Stack Integration

```bash
./install-stack.sh /path/to/ancroo-stack
```

Compose overlays in `module/`: `compose.yml`, `compose.build.yml`, `compose.ports.yml`, `compose.traefik.yml`, `compose.sso.yml`.
