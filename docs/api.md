# Ancroo Backend — API Reference

Full interactive API documentation is available at `<server-url>/api/docs` (Swagger UI) while the server is running.

## Public Endpoints

| Method | Endpoint                           | Description                            |
| ------ | ---------------------------------- | -------------------------------------- |
| `GET`  | `/health`                          | Health check                           |
| `GET`  | `/api/v1/about`                    | Version and build info                 |
| `GET`  | `/api/v1/workflows`               | List available workflows               |
| `GET`  | `/api/v1/workflows/{slug}`        | Get workflow details                   |
| `POST` | `/api/v1/workflows/{slug}/execute` | Execute a workflow with input          |
| `POST` | `/api/v1/transcribe`              | Transcribe an audio file (default STT) |

## Admin Endpoints

### Workflows

| Method | Endpoint                              | Description                       |
| ------ | ------------------------------------- | --------------------------------- |
| `POST` | `/admin/api/import-workflow`          | Import a workflow from JSON       |

### LLM Providers

| Method           | Endpoint                                      | Description                           |
| ---------------- | --------------------------------------------- | ------------------------------------- |
| `GET`            | `/api/v1/admin/llm-providers`                 | List all configured LLM providers     |
| `POST`           | `/api/v1/admin/llm-providers`                 | Add a new provider                    |
| `PUT`            | `/api/v1/admin/llm-providers/{id}`            | Update a provider                     |
| `DELETE`         | `/api/v1/admin/llm-providers/{id}`            | Remove a provider                     |
| `GET`            | `/api/v1/admin/llm-providers/{id}/health`     | Test provider connectivity            |
| `GET`            | `/api/v1/admin/llm-providers/{id}/models`     | List available models                 |
| `GET/PUT/DELETE` | `/api/v1/admin/workflows/{slug}/llm-provider` | Manage workflow ↔ provider assignment |

### STT Providers

| Method           | Endpoint                                      | Description                           |
| ---------------- | --------------------------------------------- | ------------------------------------- |
| `GET`            | `/api/v1/admin/stt-providers`                 | List all configured STT providers     |
| `POST`           | `/api/v1/admin/stt-providers`                 | Add a new provider                    |
| `PUT`            | `/api/v1/admin/stt-providers/{id}`            | Update a provider                     |
| `DELETE`         | `/api/v1/admin/stt-providers/{id}`            | Remove a provider                     |
| `GET`            | `/api/v1/admin/stt-providers/{id}/health`     | Test provider connectivity            |
| `GET`            | `/api/v1/admin/stt-providers/{id}/models`     | List available models                 |
| `GET/PUT/DELETE` | `/api/v1/admin/workflows/{slug}/stt-provider` | Manage workflow ↔ provider assignment |

### Tool Providers (n8n, etc.)

| Method   | Endpoint                                | Description                         |
| -------- | --------------------------------------- | ----------------------------------- |
| `GET`    | `/api/v1/admin/tools`                   | List all registered tool providers  |
| `POST`   | `/api/v1/admin/tools`                   | Register a new tool provider        |
| `PUT`    | `/api/v1/admin/tools/{id}`              | Update a tool provider              |
| `DELETE` | `/api/v1/admin/tools/{id}`              | Remove a tool provider              |
| `GET`    | `/api/v1/admin/tools/{id}/health`       | Test provider connectivity          |
| `GET`    | `/api/v1/admin/tools/{id}/flows`        | Discover available flows            |
| `POST`   | `/api/v1/admin/tools/{id}/flows/import` | Import a flow as an Ancroo workflow |
| `POST`   | `/api/v1/admin/tools/{id}/sync`         | Sync workflows with external flows  |
