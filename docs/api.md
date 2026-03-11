# Ancroo Backend — API Reference

Full interactive API documentation is available at `<server-url>/api/docs` (Swagger UI) while the server is running.

## Authentication

All public endpoints require an API key passed as a header:

```
Authorization: Bearer <api-key>
```

API keys are managed in the Admin UI under **Settings → API Keys**.

---

## Public Endpoints

### Health & Info

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| `GET` | `/health` | Health check — returns `{"status": "ok"}` |
| `GET` | `/api/v1/about` | Version and build info |

### Workflows

#### `GET /api/v1/workflows`

List all available workflows.

**Response:**
```json
{
  "workflows": [
    {
      "id": "uuid",
      "slug": "grammar-fix",
      "name": "Grammar Fix",
      "description": "Corrects grammar and spelling",
      "category": "text",
      "default_hotkey": "ctrl+shift+g",
      "input_type": "text",
      "output_type": "text",
      "execution_type": "script",
      "version": "1",
      "workflow_type": "text_transformation",
      "recipe": { "collect": ["text_selection"] },
      "output_action": "replace_selection",
      "sync_status": "manual"
    }
  ],
  "total": 1,
  "synced_at": "2025-01-01T00:00:00Z"
}
```

#### `GET /api/v1/workflows/{slug}`

Get full details for a single workflow (includes `timeout_seconds`, `created_at`, `updated_at`).

#### `GET /api/v1/workflows/sync/check?since=<ISO8601>`

Incremental sync — returns only workflows updated after `since`. Omit `since` to get all.

#### `GET /api/v1/workflows/hotkeys/settings`

List all hotkey settings for the current user.

**Response:**
```json
[
  {
    "workflow_id": "uuid",
    "workflow_slug": "grammar-fix",
    "workflow_name": "Grammar Fix",
    "hotkey": "ctrl+shift+g",
    "is_enabled": true
  }
]
```

#### `PUT /api/v1/workflows/hotkeys/settings`

Update a hotkey setting.

**Request:**
```json
{
  "workflow_id": "uuid",
  "custom_hotkey": "ctrl+shift+x",
  "is_enabled": true
}
```

### Execute

#### `POST /api/v1/workflows/{slug}/execute`

Execute a workflow with text or structured input.

**Request:**
```json
{
  "input_data": {
    "text": "Selected text from the browser",
    "html": "<p>Optional HTML version</p>",
    "clipboard": "Optional clipboard content",
    "fields": { "email": "user@example.com" },
    "context": { "url": "https://example.com", "title": "Page Title" }
  },
  "client_version": "1.0.0",
  "client_platform": "chrome"
}
```

**Response:**
```json
{
  "execution_id": "uuid",
  "status": "success",
  "result": {
    "text": "Corrected output text",
    "action": "replace_selection",
    "success": true,
    "error": null,
    "metadata": {}
  },
  "duration_ms": 842
}
```

#### `POST /api/v1/workflows/{slug}/execute-upload`

Execute a speech-to-text workflow with an audio file upload.

**Request:** `multipart/form-data`
- `file` — audio file (WAV, MP3, WebM, OGG; max size per workflow config)
- `input_data` — JSON string with context fields
- `client_version` — string
- `client_platform` — string

**Response:** Same as `/execute`.

### Transcribe (Direct)

#### `POST /api/v1/transcribe`

Transcribe an audio file using the default STT provider. Does not require a workflow.

**Request:** `multipart/form-data`
- `file` — audio file

**Response:**
```json
{ "text": "Transcribed text here" }
```

---

## Admin API

### Workflow Import

#### `POST /admin/api/import-workflow`

Import a workflow from a metadata JSON object. Idempotent — re-importing an existing slug returns `already_exists`.

**Request:**
```json
{
  "slug": "grammar-fix",
  "name": "Grammar Fix",
  "workflow_type": "text_transformation",
  "description": "...",
  "category": "text",
  "input_sources": ["text_selection"],
  "output_action": "replace_selection",
  "requires": ["llm"],
  "llm_prompt": "Fix the grammar of the following text:\n\n{{ text }}",
  "llm_temperature": 0.3
}
```

### LLM Providers

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| `GET` | `/api/v1/admin/llm-providers` | List all configured LLM providers |
| `POST` | `/api/v1/admin/llm-providers` | Add a new provider |
| `PUT` | `/api/v1/admin/llm-providers/{id}` | Update a provider |
| `DELETE` | `/api/v1/admin/llm-providers/{id}` | Remove a provider |
| `GET` | `/api/v1/admin/llm-providers/{id}/health` | Test provider connectivity |
| `GET` | `/api/v1/admin/llm-providers/{id}/models` | List available models |

### STT Providers

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| `GET` | `/api/v1/admin/stt-providers` | List all configured STT providers |
| `POST` | `/api/v1/admin/stt-providers` | Add a new provider |
| `PUT` | `/api/v1/admin/stt-providers/{id}` | Update a provider |
| `DELETE` | `/api/v1/admin/stt-providers/{id}` | Remove a provider |
| `GET` | `/api/v1/admin/stt-providers/{id}/health` | Test provider connectivity |
| `GET` | `/api/v1/admin/stt-providers/{id}/models` | List available models |

### Tool Providers (n8n)

| Method | Endpoint | Description |
| ------ | -------- | ----------- |
| `GET` | `/api/v1/admin/tools` | List all registered tool providers |
| `POST` | `/api/v1/admin/tools` | Register a new tool provider |
| `PUT` | `/api/v1/admin/tools/{id}` | Update a tool provider |
| `DELETE` | `/api/v1/admin/tools/{id}` | Remove a tool provider |
| `GET` | `/api/v1/admin/tools/{id}/health` | Test provider connectivity |
| `GET` | `/api/v1/admin/tools/{id}/flows` | Discover available flows |
| `POST` | `/api/v1/admin/tools/{id}/flows/import` | Import a flow as an Ancroo workflow |
| `POST` | `/api/v1/admin/tools/{id}/sync` | Sync workflows with external flows |
