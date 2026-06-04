# Speech to Text

**Type:** `speech_to_text` (STT)
**Hotkey:** `Alt+Shift+R`

Records audio and transcribes it to text using Whisper. The transcription is copied to clipboard.

Two GPU variants are provided — import the one matching your hardware:

| Variant | STT model file | Workflow file | GPU |
|---------|---------------|---------------|-----|
| ROCm | `stt-model-rocm.json` | `workflow-rocm.json` | AMD (Whisper-ROCm) |
| CUDA | `stt-model-cuda.json` | `workflow-cuda.json` | NVIDIA (Speaches) |

## Files

| File | Entity type | Purpose |
|------|-------------|---------|
| `workflow-rocm.json` | workflow | Workflow definition (ROCm) |
| `workflow-cuda.json` | workflow | Workflow definition (CUDA) |
| `category.json` | category | Category "voice" |
| `stt-model-rocm.json` | stt_model | Whisper-ROCm provider |
| `stt-model-cuda.json` | stt_model | Speaches CUDA provider |
| `demo.html` | — | Interactive demo page |

## Import

### ROCm (AMD GPU)

```bash
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @category.json
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @stt-model-rocm.json
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @workflow-rocm.json
```

### CUDA (NVIDIA GPU)

```bash
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @category.json
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @stt-model-cuda.json
curl -X POST http://localhost:8900/admin/api/import -H "Content-Type: application/json" -d @workflow-cuda.json
```

Import order: category → stt-model → workflow (dependencies first).
