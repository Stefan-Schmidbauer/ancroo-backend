# Name Formatter

**Type:** `tool` (n8n webhook)

Reads name and email fields from a form, sends them to n8n for formatting, and returns a greeting. Shows a notification with the result.

## Files

| File | Entity type | Purpose |
|------|-------------|---------|
| `workflow.json` | workflow | Workflow definition |
| `category.json` | category | Category "automation" |
| `tool.json` | tool | n8n webhook tool |
| `n8n-workflow.json` | — | n8n flow definition (import into n8n) |
| `demo.html` | — | Interactive demo page |

## Import

```bash
# 1. Import into Ancroo Backend
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @category.json
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @tool.json
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @workflow.json

# 2. Import n8n-workflow.json into n8n separately (via n8n UI or API)
```

Import order: category → tool → workflow (dependencies first).
After import, set the tool's `endpoint_url` to the n8n webhook URL via admin UI.
