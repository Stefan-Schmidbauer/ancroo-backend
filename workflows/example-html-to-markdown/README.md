# HTML to Markdown

**Type:** `tool` (Ancroo Runner plugin)

Converts selected HTML to clean Markdown using the Ancroo Runner `html-to-markdown` plugin. Result is copied to clipboard.

## Files

| File | Entity type | Purpose |
|------|-------------|---------|
| `workflow.json` | workflow | Workflow definition |
| `category.json` | category | Category "text" |
| `tool.json` | tool | AR plugin endpoint |
| `demo.html` | — | Interactive demo page |

## Import

```bash
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @category.json
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @tool.json
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @workflow.json
```

Import order: category → tool → workflow (dependencies first).
