# Ancroo Workflows

This directory contains workflow definitions that can be imported into
the Ancroo backend via the admin UI or API.  Each workflow lives in its own
subdirectory with individual export files per entity type.

---

## Naming convention

**Default = private.**  Only directories with the `example-` prefix are
tracked in git and visible on GitHub.

| Pattern | Visibility | Purpose |
|---------|------------|---------|
| `example-*/` | **Public** (tracked) | Example workflows shipped with the project |
| Everything else | **Private** (gitignored) | Internal, customer-specific, or regulated-domain workflows |
| `*.html` (root level) | **Private** (gitignored) | Internal demo pages |

---

## How it works

Each workflow directory contains separate JSON files for every entity the
workflow depends on.  Import them in dependency order (categories first,
then models/tools, then workflows).

### Via curl

```bash
cd workflows/example-grammar-fix/
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @category.json
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @llm-model.json
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @workflow.json
```

### Via Admin UI

Upload each JSON file individually via **Admin → Import / Export**.

The import is **idempotent** — importing the same file twice skips existing
entities (no duplicates).

---

## Directory structure

```
workflows/
├── README.md
├── example-grammar-fix/
│   ├── README.md
│   ├── workflow-rocm.json     ← workflow (ROCm)
│   ├── workflow-cuda.json     ← workflow (CUDA)
│   ├── category.json          ← category "text"
│   ├── llm-model-rocm.json   ← Ollama-ROCm provider
│   ├── llm-model-cuda.json   ← Ollama-CUDA provider
│   └── demo.html
├── example-speech-to-text/
│   ├── README.md
│   ├── workflow-rocm.json     ← workflow (ROCm)
│   ├── workflow-cuda.json     ← workflow (CUDA)
│   ├── category.json          ← category "voice"
│   ├── stt-model-rocm.json   ← Whisper-ROCm provider
│   ├── stt-model-cuda.json   ← Speaches CUDA provider
│   └── demo.html
├── example-html-to-markdown/
│   ├── README.md
│   ├── workflow.json
│   ├── category.json          ← category "text"
│   ├── tool.json              ← AR plugin
│   └── demo.html
├── example-webpage-to-ebook/
│   ├── README.md
│   ├── workflow.json
│   ├── category.json          ← category "text"
│   └── tool.json              ← AR plugin
├── example-contact-form-capture/
│   ├── README.md
│   ├── workflow.json
│   ├── category.json          ← category "automation"
│   ├── tool.json              ← n8n webhook
│   ├── n8n-workflow.json      ← n8n flow (import into n8n)
│   └── demo.html
├── example-name-formatter/
│   ├── README.md
│   ├── workflow.json
│   ├── category.json          ← category "automation"
│   ├── tool.json              ← n8n webhook
│   ├── n8n-workflow.json      ← n8n flow (import into n8n)
│   └── demo.html
└── example-freight-calculator/
    ├── README.md
    ├── workflow.json
    ├── category.json          ← category "automation"
    ├── tool.json              ← n8n webhook
    ├── n8n-workflow.json      ← n8n flow (import into n8n)
    └── demo.html
```

---

## JSON format

Each JSON file contains a single entity with a `_type` discriminator:

| File | `_type` | Required fields | References |
|------|---------|-----------------|------------|
| `category.json` | `category` | `name`, `icon` | — |
| `llm-model.json` | `llm_model` | `name`, `provider_type`, `base_url`, `model_id` | — |
| `stt-model.json` | `stt_model` | `name`, `provider_type`, `base_url`, `model_id` | — |
| `tool.json` | `tool` | `name`, `tool_type`, `endpoint_url` | — |
| `workflow.json` | `workflow` | `slug`, `name`, `workflow_type` | `category_name`, `llm_model_name`, `stt_model_name`, `tool_name` |

Workflows reference their dependencies **by name**.  The referenced entity
must exist in the database at import time.

**Import order:** category → llm_model / stt_model / tool → workflow

### Secrets

API keys (`api_key`, `n8n_api_key`) are **never exported**.  After importing
on a new instance, set API keys manually via the admin edit forms.

---

## Adapting for your environment

The example files use default Docker service names (e.g.
`http://ollama-rocm:11434`).  If your setup differs:

1. Import the files as-is
2. Edit the model/tool via the admin UI to update URLs
3. Or: edit the JSON file before importing

---

## Workflow types

### text_transformation (LLM)

Uses an LLM model to transform selected text.
Example: [example-grammar-fix](example-grammar-fix/)

### speech_to_text (STT)

Records audio and transcribes it using an STT model.
Example: [example-speech-to-text](example-speech-to-text/)

### tool (AR plugin)

Calls an Ancroo Runner plugin endpoint.
Examples: [example-html-to-markdown](example-html-to-markdown/), [example-webpage-to-ebook](example-webpage-to-ebook/)

### tool (n8n webhook)

Calls an n8n webhook for custom processing logic.
Examples: [example-contact-form-capture](example-contact-form-capture/), [example-name-formatter](example-name-formatter/), [example-freight-calculator](example-freight-calculator/)

For n8n workflows, import `n8n-workflow.json` into n8n separately, then set
the tool's `endpoint_url` to the resulting webhook URL.
