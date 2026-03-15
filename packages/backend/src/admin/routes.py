"""Admin GUI routes — Jinja2 + HTMX."""

import json
import re
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.version import get_version_info
from src.db.session import get_db
from src.db.models import LLMProvider as LLMProviderModel, STTProvider as STTProviderModel, ToolProvider as ToolProviderModel, Workflow
from src.admin import importer, service
from src.execution.presets import build_llm_target, build_n8n_target, build_stt_target, build_recipe
from src.execution.http_executor import execute_http_workflow, HttpExecutionError
from src.integrations import ollama, registry, sync
from src.integrations.ollama import OllamaError
from src.integrations.tool_provider import ToolProviderError
from src.integrations.llm_provider import check_provider_health, list_provider_models, LLMProviderError
from src.integrations.stt_provider import (
    check_provider_health as check_stt_health,
    list_provider_models as list_stt_models,
    STTProviderError,
)
from src.workflows.pipeline_executor import execute_pipeline, PipelineExecutionError
from src.api.v1.dependencies import get_current_user
from src.crypto import encrypt_api_key
from src.security import validate_provider_url

DbSession = Annotated[AsyncSession, Depends(get_db)]

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


async def require_admin(request: Request, db: Annotated[AsyncSession, Depends(get_db)]):
    """Require an authenticated admin user for all admin GUI routes."""
    user = await get_current_user(request, db)
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


_FLASH_MESSAGES = {
    "created": ("Created successfully.", "success"),
    "updated": ("Updated successfully.", "success"),
    "deleted": ("Deleted successfully.", "success"),
}


def _flash_context(request: Request) -> dict:
    """Extract flash message from query params for template context."""
    key = request.query_params.get("flash", "")
    msg, msg_type = _FLASH_MESSAGES.get(key, (None, None))
    if msg:
        return {"flash_message": msg, "flash_type": msg_type}
    return {}


# --- Dashboard ---

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: DbSession):
    """Admin dashboard showing all workflows and stats."""
    workflows = await service.list_workflows(db)
    stats = await service.get_workflow_stats(db)
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "workflows": workflows,
        "stats": stats,
        **_flash_context(request),
    })


# --- Workflow List (redirect to dashboard) ---

@router.get("/workflows")
async def workflows_list(request: Request):
    """Redirect /admin/workflows to the dashboard which lists all workflows."""
    return RedirectResponse(url="/admin/", status_code=307)


# --- Create Workflow (Wizard) ---

@router.get("/workflows/new", response_class=HTMLResponse)
async def new_workflow_form(request: Request):
    """Show workflow creation wizard — step 1: choose type."""
    return templates.TemplateResponse("workflow_wizard.html", {
        "request": request,
    })


@router.get("/workflows/new/form", response_class=HTMLResponse)
async def workflow_type_form(request: Request, db: DbSession, type: str = "text_transformation"):
    """HTMX partial: Return type-specific form fields."""
    providers = []
    llm_providers = []
    stt_providers = []

    if type == "text_transformation":
        result = await db.execute(
            select(LLMProviderModel).where(LLMProviderModel.is_active == True).order_by(LLMProviderModel.name)
        )
        llm_providers = list(result.scalars().all())
        template = "partials/workflow_type_text.html"
    elif type == "workflow_trigger":
        providers = await registry.list_providers(db)
        template = "partials/workflow_type_trigger.html"
    elif type == "speech_to_text":
        result = await db.execute(
            select(STTProviderModel).where(STTProviderModel.is_active == True).order_by(STTProviderModel.name)
        )
        stt_providers = list(result.scalars().all())
        template = "partials/workflow_type_whisper.html"
    else:
        template = "partials/workflow_type_custom.html"

    return templates.TemplateResponse(template, {
        "request": request,
        "providers": providers,
        "llm_providers": llm_providers,
        "stt_providers": stt_providers,
        "edit_mode": False,
        "workflow": None,
    })


@router.get("/workflows/new/llm-models", response_class=HTMLResponse)
async def workflow_llm_models(
    request: Request,
    db: DbSession,
    llm_provider_id: UUID | None = Query(None),
    selected: str = Query(""),
):
    """HTMX: Return <option> elements for available LLM models of the selected provider."""
    fallback = '<option value="">-- uses provider default --</option>'
    if not llm_provider_id:
        return HTMLResponse(fallback)
    provider = await db.get(LLMProviderModel, llm_provider_id)
    if not provider:
        return HTMLResponse(fallback)

    if provider.default_model:
        empty = f'<option value="">-- uses provider default ({provider.default_model}) --</option>'
    else:
        empty = '<option value="">-- no provider default; select a model --</option>'

    try:
        models = await list_provider_models(provider)
    except LLMProviderError:
        return HTMLResponse('<option value="">-- could not load models --</option>')
    options = empty
    for model in models:
        sel = ' selected' if model == selected else ''
        options += f'<option value="{model}"{sel}>{model}</option>'
    return HTMLResponse(options)


@router.post("/workflows")
async def create_workflow_route(
    request: Request,
    db: DbSession,
    name: str = Form(...),
    description: str = Form(""),
    workflow_type: str = Form("text_transformation"),
    # Text-Transformation fields (provider-based)
    llm_provider_id: str = Form(""),
    llm_model: str = Form(""),
    prompt_template: str = Form(""),
    temperature: float = Form(0.3),
    # Workflow-Trigger fields
    trigger_system: str = Form(""),
    trigger_flow_url: str = Form(""),
    input_sources: str = Form("text_selection"),
    form_fields_json: str = Form("[]"),
    output_fields_json: str = Form("[]"),
    # Custom fields
    target_url: str = Form(""),
    target_method: str = Form("POST"),
    target_headers: str = Form(""),
    payload_template: str = Form(""),
    response_mapping: str = Form(""),
    # Speech-to-Text fields (provider-based)
    stt_provider_id: str = Form(""),
    stt_model: str = Form(""),
    stt_language: str = Form(""),
    # Common
    output_action: str = Form("replace_selection"),
    category: str = Form("text"),
    default_hotkey: str = Form(""),
    # Legacy fallback
    steps_json: str = Form("[]"),
):
    """Create a new workflow from wizard form data."""
    user = await get_current_user(request, db)

    # Parse input sources
    sources = [s.strip() for s in input_sources.split(",") if s.strip()]

    # Parse form fields
    try:
        form_fields = json.loads(form_fields_json)
    except json.JSONDecodeError:
        form_fields = []

    # Provider IDs (parsed from form strings)
    parsed_llm_provider_id = UUID(llm_provider_id) if llm_provider_id else None
    parsed_stt_provider_id = UUID(stt_provider_id) if stt_provider_id else None

    # Parse output fields (shared by all types that support fill_fields)
    try:
        output_fields = json.loads(output_fields_json)
    except json.JSONDecodeError:
        output_fields = []

    if workflow_type == "text_transformation":
        recipe = build_recipe(sources, form_fields if form_fields else None,
                              output_fields if output_fields else None)
        target_config = build_llm_target(
            prompt_template=prompt_template,
            temperature=temperature,
        )
        output_action_val = output_action

    elif workflow_type == "workflow_trigger":
        recipe = build_recipe(sources, form_fields if form_fields else None,
                              output_fields if output_fields else None)
        target_config = build_n8n_target(trigger_flow_url)
        output_action_val = output_action

    elif workflow_type == "custom":
        recipe = build_recipe(sources, form_fields if form_fields else None,
                              output_fields if output_fields else None)
        # Parse headers
        headers = {"Content-Type": "application/json"}
        if target_headers.strip():
            try:
                headers = json.loads(target_headers)
            except json.JSONDecodeError:
                for line in target_headers.strip().split("\n"):
                    if ":" in line:
                        k, v = line.split(":", 1)
                        headers[k.strip()] = v.strip()

        target_config = {
            "url": target_url,
            "method": target_method,
            "headers": headers,
            "payload_template": payload_template,
            "response_mapping": response_mapping,
            "timeout": 120,
        }
        output_action_val = output_action

    elif workflow_type == "speech_to_text":
        recipe = build_recipe(
            ["audio"],
            file_config={
                "accept": "audio/*",
                "max_size_mb": 50,
                "label": "Audio recording",
                "required": True,
            },
        )
        target_config = build_stt_target(
            language=stt_language or None,
        )
        output_action_val = output_action

    else:
        # Legacy pipeline mode
        try:
            steps = json.loads(steps_json)
        except json.JSONDecodeError:
            steps = []
        workflow = await service.create_workflow(
            db=db, name=name, description=description,
            category=category, output_type=output_action,
            pipeline_steps=steps, created_by=user.id,
        )
        await db.commit()
        return RedirectResponse(f"/admin/workflows/{workflow.slug}?flash=created", status_code=303)

    workflow = await service.create_workflow(
        db=db,
        name=name,
        description=description,
        category=category,
        output_type=output_action_val,
        created_by=user.id,
        workflow_type=workflow_type,
        recipe=recipe,
        target_config=target_config,
        output_action=output_action_val,
        default_hotkey=default_hotkey or None,
        llm_provider_id=parsed_llm_provider_id,
        llm_model=llm_model.strip() or None,
        stt_provider_id=parsed_stt_provider_id,
        stt_model=stt_model.strip() or None,
    )
    await db.commit()
    return RedirectResponse(f"/admin/workflows/{workflow.slug}?flash=created", status_code=303)


# --- Legacy Create (pipeline) ---

@router.get("/workflows/new/legacy", response_class=HTMLResponse)
async def new_legacy_workflow_form(request: Request):
    """Show legacy pipeline workflow form."""
    models = []
    try:
        model_list = await ollama.list_models()
        models = [m.get("name", m.get("model", "")) for m in model_list]
    except OllamaError:
        pass
    return templates.TemplateResponse("workflow_form.html", {
        "request": request,
        "workflow": None,
        "models": models,
        "edit_mode": False,
    })


# --- Import Workflow ---


@router.get("/import", response_class=HTMLResponse)
async def import_page(request: Request):
    """Workflow import page — upload a JSON file."""
    return templates.TemplateResponse("import.html", {"request": request})


@router.post("/api/import-workflow")
async def api_import_workflow(request: Request, db: DbSession):
    """Import a workflow from a JSON body.

    Used by:
    - Admin UI (fetch from JavaScript)
    - Install script (curl -d @file.json)

    Returns HTMX partial when called from browser, JSON otherwise.
    """
    try:
        meta = await request.json()
    except Exception:
        result = importer.ImportResult(status="error", message="Invalid JSON body")
        if request.headers.get("HX-Request"):
            return templates.TemplateResponse(
                "partials/import_workflow_result.html",
                {"request": request, "result": result},
            )
        return JSONResponse(result.to_dict(), status_code=400)

    result = await importer.import_workflow(db, meta)
    await db.commit()

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            "partials/import_workflow_result.html",
            {"request": request, "result": result},
        )
    status_code = 200 if result.status != "error" else 400
    return JSONResponse(result.to_dict(), status_code=status_code)


@router.post("/import", response_class=HTMLResponse)
async def import_upload(request: Request, db: DbSession, file: UploadFile = File(...)):
    """Import a workflow from a file upload (form POST)."""
    content = await file.read()
    try:
        meta = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return templates.TemplateResponse("import.html", {
            "request": request,
            "flash_message": f"Invalid JSON file: {e}",
            "flash_type": "error",
        })

    result = await importer.import_workflow(db, meta)
    await db.commit()

    flash_map = {
        "created": ("success", f"Workflow '{result.name}' imported successfully."),
        "already_exists": ("success", f"Workflow '{result.slug}' already exists."),
        "created_inactive": ("success", f"Workflow '{result.name}' imported (inactive — {result.message})."),
        "reprovisioned": ("success", f"Workflow '{result.name}' reprovisioned."),
        "error": ("error", f"Import failed: {result.message}"),
    }
    flash_type, flash_msg = flash_map.get(result.status, ("error", str(result.status)))

    return templates.TemplateResponse("import.html", {
        "request": request,
        "flash_message": flash_msg,
        "flash_type": flash_type,
    })


# --- View / Edit Workflow ---

@router.get("/workflows/{slug}", response_class=HTMLResponse)
async def workflow_detail(request: Request, slug: str, db: DbSession):
    """Show workflow detail page."""
    workflow = await service.get_workflow(db, slug)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    executions = await service.get_recent_executions(db, workflow.id)

    return templates.TemplateResponse("workflow_detail.html", {
        "request": request,
        "workflow": workflow,
        "executions": executions,
        **_flash_context(request),
    })


@router.get("/workflows/{slug}/demo")
async def workflow_demo(request: Request, slug: str, db: DbSession):
    """Redirect to the static demo page for a workflow."""
    workflow = await service.get_workflow(db, slug)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if not workflow.demo_url:
        raise HTTPException(status_code=404, detail="No demo page configured for this workflow")

    return RedirectResponse(url=f"/demos/{slug}/{workflow.demo_url}")


@router.get("/workflows/{slug}/edit", response_class=HTMLResponse)
async def edit_workflow_form(request: Request, slug: str, db: DbSession):
    """Show edit workflow form."""
    workflow = await service.get_workflow(db, slug)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Use type-aware edit template for generic workflows
    if workflow.workflow_type:
        providers = []
        llm_providers = []
        stt_providers = []

        if workflow.workflow_type == "workflow_trigger":
            providers = await registry.list_providers(db)
        elif workflow.workflow_type == "text_transformation":
            result = await db.execute(
                select(LLMProviderModel).where(LLMProviderModel.is_active == True).order_by(LLMProviderModel.name)
            )
            llm_providers = list(result.scalars().all())
        elif workflow.workflow_type == "speech_to_text":
            result = await db.execute(
                select(STTProviderModel).where(STTProviderModel.is_active == True).order_by(STTProviderModel.name)
            )
            stt_providers = list(result.scalars().all())

        return templates.TemplateResponse("workflow_edit.html", {
            "request": request,
            "workflow": workflow,
            "providers": providers,
            "llm_providers": llm_providers,
            "stt_providers": stt_providers,
            "edit_mode": True,
        })

    # Legacy pipeline workflow: use old form
    models = []
    try:
        model_list = await ollama.list_models()
        models = [m.get("name", m.get("model", "")) for m in model_list]
    except OllamaError:
        pass
    return templates.TemplateResponse("workflow_form.html", {
        "request": request,
        "workflow": workflow,
        "models": models,
        "edit_mode": True,
    })


@router.post("/workflows/{slug}/update")
async def update_workflow(
    request: Request,
    slug: str,
    db: DbSession,
    name: str = Form(...),
    description: str = Form(""),
    category: str = Form("text"),
    is_active: str = Form("off"),
    # New generic fields
    workflow_type: str = Form(""),
    prompt_template: str = Form(""),
    temperature: float = Form(0.3),
    default_hotkey: str = Form(""),
    # Provider fields
    llm_provider_id: str = Form(""),
    llm_model: str = Form(""),
    stt_provider_id: str = Form(""),
    stt_model: str = Form(""),
    stt_language: str = Form(""),
    # Trigger fields
    trigger_system: str = Form(""),
    trigger_flow_url: str = Form(""),
    input_sources: str = Form("text_selection"),
    form_fields_json: str = Form("[]"),
    output_fields_json: str = Form("[]"),
    # Custom fields
    target_url: str = Form(""),
    target_method: str = Form("POST"),
    target_headers: str = Form(""),
    payload_template: str = Form(""),
    response_mapping: str = Form(""),
    output_action: str = Form("replace_selection"),
    # Legacy fallback
    output_type: str = Form("replace_selection"),
    steps_json: str = Form("[]"),
):
    """Update workflow from form data."""
    target_config = None
    recipe = None
    output_action_val = None
    pipeline_steps = None

    # Provider IDs (parsed from form strings)
    parsed_llm_provider_id = UUID(llm_provider_id) if llm_provider_id else None
    parsed_stt_provider_id = UUID(stt_provider_id) if stt_provider_id else None

    # Parse sources, form fields, and output fields (shared by all types)
    sources = [s.strip() for s in input_sources.split(",") if s.strip()]
    try:
        form_fields = json.loads(form_fields_json)
    except json.JSONDecodeError:
        form_fields = []
    try:
        output_fields = json.loads(output_fields_json)
    except json.JSONDecodeError:
        output_fields = []

    if workflow_type == "text_transformation":
        recipe = build_recipe(sources, form_fields if form_fields else None,
                              output_fields if output_fields else None)
        target_config = build_llm_target(
            prompt_template=prompt_template,
            temperature=temperature,
        )
        output_action_val = output_action

    elif workflow_type == "workflow_trigger":
        recipe = build_recipe(sources, form_fields if form_fields else None,
                              output_fields if output_fields else None)
        target_config = build_n8n_target(trigger_flow_url)
        output_action_val = output_action

    elif workflow_type == "custom":
        recipe = build_recipe(sources, form_fields if form_fields else None,
                              output_fields if output_fields else None)
        headers = {"Content-Type": "application/json"}
        if target_headers.strip():
            try:
                headers = json.loads(target_headers)
            except json.JSONDecodeError:
                for line in target_headers.strip().split("\n"):
                    if ":" in line:
                        k, v = line.split(":", 1)
                        headers[k.strip()] = v.strip()
        target_config = {
            "url": target_url,
            "method": target_method,
            "headers": headers,
            "payload_template": payload_template,
            "response_mapping": response_mapping,
            "timeout": 120,
        }
        output_action_val = output_action

    elif workflow_type == "speech_to_text":
        recipe = build_recipe(
            ["audio"],
            file_config={
                "accept": "audio/*",
                "max_size_mb": 50,
                "label": "Audio recording",
                "required": True,
            },
        )
        target_config = build_stt_target(
            language=stt_language or None,
        )
        output_action_val = output_action

    else:
        # Legacy pipeline workflow
        try:
            pipeline_steps = json.loads(steps_json)
        except json.JSONDecodeError:
            pipeline_steps = []

    # For new workflow types, keep output_type in sync with output_action.
    # Legacy pipeline workflows use output_type from the form directly.
    effective_output_type = output_action_val if output_action_val else output_type

    workflow = await service.update_workflow(
        db=db,
        slug=slug,
        name=name,
        description=description,
        category=category,
        output_type=effective_output_type,
        pipeline_steps=pipeline_steps,
        is_active=is_active == "on",
        workflow_type=workflow_type or None,
        recipe=recipe,
        target_config=target_config,
        output_action=output_action_val,
        default_hotkey=default_hotkey or None,
        llm_provider_id=parsed_llm_provider_id,
        llm_model=llm_model.strip() or None,
        stt_provider_id=parsed_stt_provider_id,
        stt_model=stt_model.strip() or None,
    )
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    await db.commit()
    return RedirectResponse(f"/admin/workflows/{workflow.slug}?flash=updated", status_code=303)


# --- Delete Workflow ---

@router.post("/workflows/{slug}/delete")
async def delete_workflow(slug: str, db: DbSession):
    """Delete a workflow."""
    deleted = await service.delete_workflow(db, slug)
    if not deleted:
        raise HTTPException(status_code=404, detail="Workflow not found")
    await db.commit()
    return RedirectResponse("/admin/?flash=deleted", status_code=303)


# --- Toggle Active (HTMX) ---

@router.post("/workflows/{slug}/toggle-active", response_class=HTMLResponse)
async def toggle_workflow_active(request: Request, slug: str, db: DbSession):
    """HTMX: Toggle workflow is_active and return updated toggle button."""
    workflow = await service.get_workflow(db, slug)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    await service.update_workflow(db, slug, is_active=not workflow.is_active)

    return templates.TemplateResponse("partials/toggle_active.html", {
        "request": request,
        "workflow": workflow,
    })


# --- Test Execution (HTMX) ---

@router.post("/workflows/{slug}/test", response_class=HTMLResponse)
async def test_workflow(
    request: Request,
    slug: str,
    db: DbSession,
    test_input: str = Form(""),
):
    """Test-execute a workflow and return result as HTML partial."""
    workflow = await service.get_workflow(db, slug)
    if not workflow:
        return templates.TemplateResponse("partials/test_result.html", {
            "request": request,
            "success": False,
            "error": "Workflow not found",
            "output": None,
            "duration_ms": None,
        })

    user = await get_current_user(request, db)
    input_data = {"text": test_input, "context": {}}

    try:
        # Use new HTTP executor for generic workflows, pipeline for legacy
        if workflow.workflow_type:
            result = await execute_http_workflow(
                workflow=workflow,
                input_data=input_data,
                db=db,
                user_id=user.id,
                client_version="admin-gui",
                client_platform="web",
            )
        else:
            result = await execute_pipeline(
                workflow=workflow,
                input_data=input_data,
                db=db,
                user_id=user.id,
                client_version="admin-gui",
                client_platform="web",
            )
        return templates.TemplateResponse("partials/test_result.html", {
            "request": request,
            "success": True,
            "error": None,
            "output": result.get("text", ""),
            "duration_ms": result.get("metadata", {}).get("duration_ms"),
        })
    except (PipelineExecutionError, HttpExecutionError) as e:
        return templates.TemplateResponse("partials/test_result.html", {
            "request": request,
            "success": False,
            "error": e.message,
            "output": None,
            "duration_ms": None,
        })


# --- Ollama Models API (for form dropdowns) ---

@router.get("/api/models")
async def get_ollama_models():
    """Return available Ollama models as JSON."""
    try:
        model_list = await ollama.list_models()
        return {"models": [m.get("name", m.get("model", "")) for m in model_list]}
    except OllamaError as e:
        return {"models": [], "error": str(e)}


# ============================================================
# Tool Provider Admin Routes
# ============================================================


@router.get("/tools", response_class=HTMLResponse)
async def tools_list(request: Request, db: DbSession):
    """Tool provider overview page."""
    providers = await registry.list_providers(db)
    return templates.TemplateResponse("tools.html", {
        "request": request,
        "providers": providers,
        **_flash_context(request),
    })


@router.get("/tools/new", response_class=HTMLResponse)
async def new_tool_form(request: Request):
    """Show register tool provider form."""
    return templates.TemplateResponse("tool_form.html", {
        "request": request,
        "provider": None,
        "edit_mode": False,
    })


@router.post("/tools")
async def create_tool_provider(
    request: Request,
    db: DbSession,
    provider_type: str = Form(...),
    name: str = Form(...),
    base_url: str = Form(...),
    api_key: str = Form(""),
):
    """Register a new tool provider."""
    validate_provider_url(base_url)
    provider = ToolProviderModel(
        provider_type=provider_type,
        name=name,
        base_url=base_url,
        api_key=encrypt_api_key(api_key) if api_key else None,
    )
    db.add(provider)
    await db.commit()
    return RedirectResponse(f"/admin/tools/{provider.id}?flash=created", status_code=303)


@router.get("/tools/{provider_id}", response_class=HTMLResponse)
async def tool_detail(request: Request, provider_id: UUID, db: DbSession):
    """Show tool provider detail page."""
    provider = await registry.get_provider_model(db, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Tool provider not found")

    # Get linked workflows
    result = await db.execute(
        select(Workflow).where(
            Workflow.tool_provider_id == provider_id,
            Workflow.execution_type == "tool",
        ).order_by(Workflow.name)
    )
    linked_workflows = list(result.scalars().all())

    return templates.TemplateResponse("tool_detail.html", {
        "request": request,
        "provider": provider,
        "linked_workflows": linked_workflows,
        **_flash_context(request),
    })


@router.get("/tools/{provider_id}/edit", response_class=HTMLResponse)
async def edit_tool_form(request: Request, provider_id: UUID, db: DbSession):
    """Show edit tool provider form."""
    provider = await registry.get_provider_model(db, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Tool provider not found")

    return templates.TemplateResponse("tool_form.html", {
        "request": request,
        "provider": provider,
        "edit_mode": True,
    })


@router.post("/tools/{provider_id}/update")
async def update_tool_provider(
    request: Request,
    provider_id: UUID,
    db: DbSession,
    name: str = Form(...),
    base_url: str = Form(...),
    api_key: str = Form(""),
    is_active: str = Form("off"),
):
    """Update a tool provider."""
    validate_provider_url(base_url)
    provider = await registry.get_provider_model(db, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Tool provider not found")

    provider.name = name
    provider.base_url = base_url
    if api_key:
        provider.api_key = encrypt_api_key(api_key)
    provider.is_active = is_active == "on"

    await db.commit()
    return RedirectResponse(f"/admin/tools/{provider_id}?flash=updated", status_code=303)


@router.post("/tools/{provider_id}/delete")
async def delete_tool_provider(provider_id: UUID, db: DbSession):
    """Delete a tool provider."""
    provider = await registry.get_provider_model(db, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Tool provider not found")

    await db.delete(provider)
    await db.commit()
    return RedirectResponse("/admin/tools?flash=deleted", status_code=303)


@router.post("/tools/{provider_id}/health-check", response_class=HTMLResponse)
async def tool_health_check(request: Request, provider_id: UUID, db: DbSession):
    """HTMX: Run health check and return partial."""
    try:
        result = await registry.check_health(db, provider_id)
        return templates.TemplateResponse("partials/health_result.html", {
            "request": request,
            "healthy": result.get("healthy", False),
            "message": result.get("message", ""),
        })
    except ToolProviderError as e:
        return templates.TemplateResponse("partials/health_result.html", {
            "request": request,
            "healthy": False,
            "message": e.message,
        })


@router.get("/tools/{provider_id}/discover", response_class=HTMLResponse)
async def discover_flows(request: Request, provider_id: UUID, db: DbSession):
    """HTMX: Discover flows from a provider and return partial."""
    try:
        flows = await sync.discover_flows(db, provider_id)
    except ToolProviderError as e:
        return HTMLResponse(
            f'<div class="text-xs bg-red-50 text-red-700 border border-red-200 rounded p-2">'
            f'Discovery failed: {e.message}</div>'
        )

    # Check which flows are already imported
    existing = await db.execute(
        select(Workflow.external_flow_id).where(
            Workflow.tool_provider_id == provider_id,
            Workflow.execution_type == "tool",
        )
    )
    imported_ids = {row[0] for row in existing.all()}

    flow_items = []
    for f in flows:
        flow_items.append({
            "id": f["id"],
            "name": f.get("name", f["id"]),
            "description": f.get("description", ""),
            "status": f.get("status", "ENABLED"),
            "trigger_type": f.get("trigger_type", ""),
            "has_webhook": f.get("has_webhook", False),
            "already_imported": f["id"] in imported_ids,
        })

    return templates.TemplateResponse("partials/flow_list.html", {
        "request": request,
        "flows": flow_items,
        "provider_id": provider_id,
    })


@router.post("/tools/{provider_id}/import", response_class=HTMLResponse)
async def import_flow(
    request: Request,
    provider_id: UUID,
    db: DbSession,
    flow_id: str = Form(...),
    flow_name: str = Form(...),
):
    """HTMX: Import a flow as an Ancroo workflow."""
    try:
        workflow = await sync.import_flow(
            db=db,
            provider_id=provider_id,
            flow_data={"id": flow_id, "name": flow_name},
        )
        return templates.TemplateResponse("partials/import_result.html", {
            "request": request,
            "flow_name": flow_name,
            "workflow_slug": workflow.slug,
        })
    except ToolProviderError as e:
        return HTMLResponse(
            f'<div class="text-xs bg-red-50 text-red-700 rounded p-2">Import failed: {e.message}</div>'
        )


@router.post("/tools/{provider_id}/sync", response_class=HTMLResponse)
async def sync_workflows(request: Request, provider_id: UUID, db: DbSession):
    """HTMX: Sync workflows with a provider."""
    try:
        report = await sync.sync_workflows(db, provider_id)
        return templates.TemplateResponse("partials/sync_result.html", {
            "request": request,
            "error": None,
            **report,
        })
    except ToolProviderError as e:
        return templates.TemplateResponse("partials/sync_result.html", {
            "request": request,
            "error": e.message,
        })


# ============================================================
# LLM Provider Admin Routes
# ============================================================


@router.get("/llm-providers", response_class=HTMLResponse)
async def llm_providers_list(request: Request, db: DbSession):
    """LLM provider overview page."""
    result = await db.execute(
        select(LLMProviderModel)
        .options(selectinload(LLMProviderModel.workflows))
        .order_by(LLMProviderModel.name)
    )
    providers = list(result.scalars().all())
    return templates.TemplateResponse("llm_providers.html", {
        "request": request,
        "providers": providers,
        **_flash_context(request),
    })


@router.get("/llm-providers/new", response_class=HTMLResponse)
async def new_llm_provider_form(request: Request):
    """Show create LLM provider form."""
    return templates.TemplateResponse("llm_provider_form.html", {
        "request": request,
        "provider": None,
        "edit_mode": False,
    })


@router.get("/llm-providers/probe-models", response_class=HTMLResponse)
async def llm_provider_probe_models(
    request: Request,
    provider_type: str = Query("ollama"),
    base_url: str = Query(""),
    api_key: str = Query(""),
):
    """HTMX: Probe available models using form field values (before provider is saved)."""
    from src.integrations.llm_provider import _ollama_list_models, _openai_list_models

    if not base_url:
        return HTMLResponse('<option value="">-- enter Base URL first --</option>')
    try:
        validate_provider_url(base_url)
    except HTTPException:
        return HTMLResponse('<option value="">-- invalid URL --</option>')
    try:
        if provider_type == "ollama":
            models = await _ollama_list_models(base_url)
        elif provider_type == "openai_compatible":
            models = await _openai_list_models(base_url, api_key or None)
        else:
            return HTMLResponse('<option value="">-- unknown provider type --</option>')
    except Exception:
        return HTMLResponse('<option value="">-- could not reach provider --</option>')
    if not models:
        return HTMLResponse('<option value="">-- no models found --</option>')
    options = '<option value="">-- no default --</option>'
    for model in models:
        options += f'<option value="{model}">{model}</option>'
    return HTMLResponse(options)


@router.post("/llm-providers")
async def create_llm_provider(
    request: Request,
    db: DbSession,
    provider_type: str = Form(...),
    name: str = Form(...),
    base_url: str = Form(...),
    api_key: str = Form(""),
    default_model: str = Form(""),
):
    """Create a new LLM provider."""
    validate_provider_url(base_url)
    provider = LLMProviderModel(
        provider_type=provider_type,
        name=name,
        base_url=base_url,
        api_key=encrypt_api_key(api_key) if api_key else None,
        default_model=default_model or None,
    )
    db.add(provider)
    await db.commit()
    return RedirectResponse(f"/admin/llm-providers/{provider.id}?flash=created", status_code=303)


@router.get("/llm-providers/{provider_id}", response_class=HTMLResponse)
async def llm_provider_detail(request: Request, provider_id: UUID, db: DbSession):
    """Show LLM provider detail page."""
    provider = await db.get(LLMProviderModel, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="LLM provider not found")

    result = await db.execute(
        select(Workflow)
        .where(Workflow.llm_provider_id == provider_id)
        .order_by(Workflow.name)
    )
    linked_workflows = list(result.scalars().all())

    return templates.TemplateResponse("llm_provider_detail.html", {
        "request": request,
        "provider": provider,
        "linked_workflows": linked_workflows,
        **_flash_context(request),
    })


@router.get("/llm-providers/{provider_id}/edit", response_class=HTMLResponse)
async def edit_llm_provider_form(request: Request, provider_id: UUID, db: DbSession):
    """Show edit LLM provider form."""
    provider = await db.get(LLMProviderModel, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="LLM provider not found")
    return templates.TemplateResponse("llm_provider_form.html", {
        "request": request,
        "provider": provider,
        "edit_mode": True,
    })


@router.post("/llm-providers/{provider_id}/update")
async def update_llm_provider(
    request: Request,
    provider_id: UUID,
    db: DbSession,
    name: str = Form(...),
    base_url: str = Form(...),
    api_key: str = Form(""),
    default_model: str = Form(""),
    is_active: str = Form("off"),
):
    """Update an LLM provider."""
    validate_provider_url(base_url)
    provider = await db.get(LLMProviderModel, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="LLM provider not found")

    provider.name = name
    provider.base_url = base_url
    if api_key:
        provider.api_key = encrypt_api_key(api_key)
    provider.default_model = default_model or None
    provider.is_active = is_active == "on"

    await db.commit()
    return RedirectResponse(f"/admin/llm-providers/{provider_id}?flash=updated", status_code=303)


@router.post("/llm-providers/{provider_id}/delete")
async def delete_llm_provider(provider_id: UUID, db: DbSession):
    """Delete an LLM provider."""
    provider = await db.get(LLMProviderModel, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="LLM provider not found")
    await db.delete(provider)
    await db.commit()
    return RedirectResponse("/admin/llm-providers?flash=deleted", status_code=303)


@router.post("/llm-providers/{provider_id}/health-check", response_class=HTMLResponse)
async def llm_provider_health_check(request: Request, provider_id: UUID, db: DbSession):
    """HTMX: Run health check and return partial."""
    from datetime import datetime, timezone
    provider = await db.get(LLMProviderModel, provider_id)
    if not provider:
        return templates.TemplateResponse("partials/health_result.html", {
            "request": request, "healthy": False, "message": "Provider not found",
        })
    result = await check_provider_health(provider)
    provider.health_status = "healthy" if result.get("healthy") else "unhealthy"
    provider.last_health_check = datetime.now(timezone.utc)
    await db.flush()
    return templates.TemplateResponse("partials/health_result.html", {
        "request": request,
        "healthy": result.get("healthy", False),
        "message": result.get("error", ""),
    })


@router.get("/llm-providers/{provider_id}/models", response_class=HTMLResponse)
async def llm_provider_list_models(request: Request, provider_id: UUID, db: DbSession):
    """HTMX: Fetch available models from provider and return partial."""
    provider = await db.get(LLMProviderModel, provider_id)
    if not provider:
        return HTMLResponse('<p class="text-xs text-red-600">Provider not found</p>')
    try:
        models = await list_provider_models(provider)
    except LLMProviderError as e:
        return HTMLResponse(
            f'<p class="text-xs text-red-600">Failed to load models: {e.message}</p>'
        )
    return templates.TemplateResponse("partials/llm_models.html", {
        "request": request,
        "models": models,
        "provider_id": provider_id,
    })


# ============================================================
# STT Provider Admin Routes
# ============================================================


@router.get("/stt-providers", response_class=HTMLResponse)
async def stt_providers_list(request: Request, db: DbSession):
    """STT provider overview page."""
    result = await db.execute(
        select(STTProviderModel)
        .options(selectinload(STTProviderModel.workflows))
        .order_by(STTProviderModel.name)
    )
    providers = list(result.scalars().all())
    return templates.TemplateResponse("stt_providers.html", {
        "request": request,
        "providers": providers,
        **_flash_context(request),
    })


@router.get("/stt-providers/new", response_class=HTMLResponse)
async def new_stt_provider_form(request: Request):
    """Show create STT provider form."""
    return templates.TemplateResponse("stt_provider_form.html", {
        "request": request,
        "provider": None,
        "edit_mode": False,
    })


@router.post("/stt-providers")
async def create_stt_provider(
    request: Request,
    db: DbSession,
    provider_type: str = Form(...),
    name: str = Form(...),
    base_url: str = Form(...),
    api_key: str = Form(""),
    default_model: str = Form(...),
    default_language: str = Form(""),
):
    """Create a new STT provider."""
    validate_provider_url(base_url)
    provider = STTProviderModel(
        provider_type=provider_type,
        name=name,
        base_url=base_url,
        api_key=encrypt_api_key(api_key) if api_key else None,
        default_model=default_model,
        default_language=default_language.strip() or None,
    )
    db.add(provider)
    await db.commit()
    return RedirectResponse(f"/admin/stt-providers/{provider.id}?flash=created", status_code=303)


@router.get("/stt-providers/{provider_id}", response_class=HTMLResponse)
async def stt_provider_detail(request: Request, provider_id: UUID, db: DbSession):
    """Show STT provider detail page."""
    provider = await db.get(STTProviderModel, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="STT provider not found")

    result = await db.execute(
        select(Workflow)
        .where(Workflow.stt_provider_id == provider_id)
        .order_by(Workflow.name)
    )
    linked_workflows = list(result.scalars().all())

    return templates.TemplateResponse("stt_provider_detail.html", {
        "request": request,
        "provider": provider,
        "linked_workflows": linked_workflows,
        **_flash_context(request),
    })


@router.get("/stt-providers/{provider_id}/edit", response_class=HTMLResponse)
async def edit_stt_provider_form(request: Request, provider_id: UUID, db: DbSession):
    """Show edit STT provider form."""
    provider = await db.get(STTProviderModel, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="STT provider not found")
    return templates.TemplateResponse("stt_provider_form.html", {
        "request": request,
        "provider": provider,
        "edit_mode": True,
    })


@router.post("/stt-providers/{provider_id}/update")
async def update_stt_provider(
    request: Request,
    provider_id: UUID,
    db: DbSession,
    name: str = Form(...),
    base_url: str = Form(...),
    api_key: str = Form(""),
    default_model: str = Form(...),
    default_language: str = Form(""),
    is_active: str = Form("off"),
):
    """Update an STT provider."""
    validate_provider_url(base_url)
    provider = await db.get(STTProviderModel, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="STT provider not found")

    provider.name = name
    provider.base_url = base_url
    if api_key:
        provider.api_key = encrypt_api_key(api_key)
    provider.default_model = default_model
    provider.default_language = default_language.strip() or None
    provider.is_active = is_active == "on"

    await db.commit()
    return RedirectResponse(f"/admin/stt-providers/{provider_id}?flash=updated", status_code=303)


@router.post("/stt-providers/{provider_id}/delete")
async def delete_stt_provider(provider_id: UUID, db: DbSession):
    """Delete an STT provider."""
    provider = await db.get(STTProviderModel, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="STT provider not found")
    await db.delete(provider)
    await db.commit()
    return RedirectResponse("/admin/stt-providers?flash=deleted", status_code=303)


@router.post("/stt-providers/{provider_id}/health-check", response_class=HTMLResponse)
async def stt_provider_health_check(request: Request, provider_id: UUID, db: DbSession):
    """HTMX: Run health check and return partial."""
    from datetime import datetime, timezone
    provider = await db.get(STTProviderModel, provider_id)
    if not provider:
        return templates.TemplateResponse("partials/health_result.html", {
            "request": request, "healthy": False, "message": "Provider not found",
        })
    result = await check_stt_health(provider)
    provider.health_status = "healthy" if result.get("healthy") else "unhealthy"
    provider.last_health_check = datetime.now(timezone.utc)
    await db.flush()
    return templates.TemplateResponse("partials/health_result.html", {
        "request": request,
        "healthy": result.get("healthy", False),
        "message": result.get("error", ""),
    })


@router.get("/stt-providers/{provider_id}/models", response_class=HTMLResponse)
async def stt_provider_list_models(request: Request, provider_id: UUID, db: DbSession):
    """HTMX: Fetch available models from STT provider and return partial."""
    provider = await db.get(STTProviderModel, provider_id)
    if not provider:
        return HTMLResponse('<p class="text-xs text-red-600">Provider not found</p>')
    try:
        models = await list_stt_models(provider)
    except STTProviderError as e:
        return HTMLResponse(
            f'<p class="text-xs text-red-600">Failed to load models: {e.message}</p>'
        )
    return templates.TemplateResponse("partials/stt_models.html", {
        "request": request,
        "models": models,
        "provider_id": provider_id,
    })


# --- About ---


@router.get("/demo", response_class=HTMLResponse)
async def demo_page(request: Request):
    """Demo page for testing text transformation workflows."""
    return templates.TemplateResponse("demo.html", {"request": request})


@router.get("/about", response_class=HTMLResponse)
async def about_page(request: Request):
    """About page showing version and build information."""
    return templates.TemplateResponse("about.html", {
        "request": request,
        **get_version_info(),
    })
