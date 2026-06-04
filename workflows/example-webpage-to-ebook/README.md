# Webpage to EPUB

**Type:** `tool` (Ancroo Runner plugin)

Converts the current webpage to an EPUB ebook file using the Ancroo Runner `webpage-to-ebook` plugin. The file is offered as download.

## Files

| File | Entity type | Purpose |
|------|-------------|---------|
| `workflow.json` | workflow | Workflow definition |
| `category.json` | category | Category "text" |
| `tool.json` | tool | AR plugin endpoint |

## Import

```bash
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @category.json
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @tool.json
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @workflow.json
```

Import order: category → tool → workflow (dependencies first).
