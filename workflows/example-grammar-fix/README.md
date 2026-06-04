# Grammar & Spelling

**Type:** `text_transformation` (LLM)
**Hotkey:** `Alt+Shift+G`

Corrects grammar and spelling errors in selected text using an LLM. The corrected text replaces the selection.

## Files

| File | Entity type | Purpose |
|------|-------------|---------|
| `workflow-rocm.json` | workflow | Workflow definition (ROCm) |
| `workflow-cuda.json` | workflow | Workflow definition (CUDA) |
| `category.json` | category | Category "text" |
| `llm-model-rocm.json` | llm_model | Ollama-ROCm provider |
| `llm-model-cuda.json` | llm_model | Ollama-CUDA provider |
| `demo.html` | — | Interactive demo page |

## Import

### ROCm (AMD GPU)

```bash
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @category.json
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @llm-model-rocm.json
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @workflow-rocm.json
```

### CUDA (NVIDIA GPU)

```bash
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @category.json
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @llm-model-cuda.json
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @workflow-cuda.json
```

Import order: category → llm-model → workflow (dependencies first).
