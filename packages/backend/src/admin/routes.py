"""Admin GUI routes — Jinja2 + HTMX."""

import json
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
from src.db.models import Category, LLMModel, STTModel, Tool, Workflow
from src.admin import importer, service
from src.integrations.llm import check_health as check_llm_health, list_models as list_llm_models, LLMError
from src.integrations.stt import check_health as check_stt_health, list_models as list_stt_models, STTError
from src.integrations.runner import sync_tools_from_runner, RunnerDiscoveryError
from src.api.v1.dependencies import get_current_user
from src.crypto import encrypt_api_key, decrypt_api_key
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


def _build_recipe(sources: list[str], form_fields: list | None = None,
                  output_fields: list | None = None,
                  file_config: dict | None = None) -> dict:
    """Build a recipe dict matching the canonical schema.

    Schema: {collect: [...sources], form_fields?: [...], output_fields?: [...], file_config?: {...}}
    `collect` is always a flat array of source strings — same format as importer.py.
    """
    recipe: dict = {"collect": sources or []}
    if form_fields:
        recipe["form_fields"] = form_fields
    if output_fields:
        recipe["output_fields"] = output_fields
    if file_config:
        recipe["file_config"] = file_config
    return recipe


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
    llm_models = []
    stt_models = []
    tools = []
    categories = await service.list_categories(db)

    if type == "text_transformation":
        result = await db.execute(
            select(LLMModel).where(LLMModel.is_active == True).order_by(LLMModel.name)
        )
        llm_models = list(result.scalars().all())
        template = "partials/workflow_type_text.html"
    elif type == "speech_to_text":
        result = await db.execute(
            select(STTModel).where(STTModel.is_active == True).order_by(STTModel.name)
        )
        stt_models = list(result.scalars().all())
        template = "partials/workflow_type_whisper.html"
    else:
        # tool, workflow_trigger, custom — all use tool dropdown
        result = await db.execute(
            select(Tool).where(Tool.is_active == True).order_by(Tool.name)
        )
        tools = list(result.scalars().all())
        template = "partials/workflow_type_tool.html"

    return templates.TemplateResponse(template, {
        "request": request,
        "llm_models": llm_models,
        "stt_models": stt_models,
        "tools": tools,
        "categories": categories,
        "edit_mode": False,
        "workflow": None,
    })


@router.post("/workflows")
async def create_workflow_route(
    request: Request,
    db: DbSession,
    name: str = Form(...),
    description: str = Form(""),
    workflow_type: str = Form("text_transformation"),
    # Text-Transformation fields
    llm_model_id: str = Form(""),
    prompt_template: str = Form(""),
    temperature: float = Form(0.7),
    # Speech-to-Text fields
    stt_model_id: str = Form(""),
    # Tool / Trigger fields
    tool_id: str = Form(""),
    # Collect config
    input_sources: str = Form("text_selection"),
    form_fields_json: str = Form("[]"),
    output_fields_json: str = Form("[]"),
    # Common
    output_action: str = Form("replace_selection"),
    category_id: str = Form(""),
    default_hotkey: str = Form(""),
    timeout_seconds: int = Form(60),
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

    # Parse output fields
    try:
        output_fields = json.loads(output_fields_json)
    except json.JSONDecodeError:
        output_fields = []

    # Parse foreign key IDs
    parsed_llm_model_id = UUID(llm_model_id) if llm_model_id else None
    parsed_stt_model_id = UUID(stt_model_id) if stt_model_id else None
    parsed_tool_id = UUID(tool_id) if tool_id else None

    if workflow_type == "speech_to_text":
        recipe = _build_recipe(
            ["audio"],
            file_config={
                "accept": "audio/*",
                "max_size_mb": 50,
                "label": "Audio recording",
                "required": True,
            },
        )
    else:
        # text_transformation, tool, workflow_trigger, custom
        recipe = _build_recipe(sources, form_fields if form_fields else None,
                               output_fields if output_fields else None)

    parsed_category_id = UUID(category_id) if category_id else None

    workflow = await service.create_workflow(
        db=db,
        name=name,
        description=description,
        category_id=parsed_category_id,
        workflow_type=workflow_type,
        recipe=recipe,
        output_action=output_action,
        default_hotkey=default_hotkey or None,
        timeout_seconds=timeout_seconds,
        created_by=user.id,
        llm_model_id=parsed_llm_model_id,
        prompt_template=prompt_template or None,
        temperature=temperature,
        stt_model_id=parsed_stt_model_id,
        tool_id=parsed_tool_id,
    )
    await db.commit()
    return RedirectResponse(f"/admin/workflows/{workflow.slug}?flash=created", status_code=303)


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

    llm_models = []
    stt_models = []
    tools = []
    categories = await service.list_categories(db)

    if workflow.workflow_type == "text_transformation":
        result = await db.execute(
            select(LLMModel).where(LLMModel.is_active == True).order_by(LLMModel.name)
        )
        llm_models = list(result.scalars().all())
    elif workflow.workflow_type == "speech_to_text":
        result = await db.execute(
            select(STTModel).where(STTModel.is_active == True).order_by(STTModel.name)
        )
        stt_models = list(result.scalars().all())
    else:
        # tool, workflow_trigger, custom — all use tool dropdown
        result = await db.execute(
            select(Tool).where(Tool.is_active == True).order_by(Tool.name)
        )
        tools = list(result.scalars().all())

    return templates.TemplateResponse("workflow_edit.html", {
        "request": request,
        "workflow": workflow,
        "llm_models": llm_models,
        "stt_models": stt_models,
        "tools": tools,
        "categories": categories,
        "edit_mode": True,
    })


@router.post("/workflows/{slug}/update")
async def update_workflow(
    request: Request,
    slug: str,
    db: DbSession,
    name: str = Form(...),
    description: str = Form(""),
    category_id: str = Form(""),
    is_active: str = Form("off"),
    # Workflow type
    workflow_type: str = Form(""),
    # Text-Transformation fields
    prompt_template: str = Form(""),
    temperature: float = Form(0.7),
    default_hotkey: str = Form(""),
    timeout_seconds: int = Form(60),
    # Model / Tool FK fields
    llm_model_id: str = Form(""),
    stt_model_id: str = Form(""),
    tool_id: str = Form(""),
    # Collect config
    input_sources: str = Form("text_selection"),
    form_fields_json: str = Form("[]"),
    output_fields_json: str = Form("[]"),
    output_action: str = Form("replace_selection"),
):
    """Update workflow from form data."""
    recipe = None

    # Parse foreign key IDs
    parsed_llm_model_id = UUID(llm_model_id) if llm_model_id else None
    parsed_stt_model_id = UUID(stt_model_id) if stt_model_id else None
    parsed_tool_id = UUID(tool_id) if tool_id else None

    # Parse sources, form fields, and output fields
    sources = [s.strip() for s in input_sources.split(",") if s.strip()]
    try:
        form_fields = json.loads(form_fields_json)
    except json.JSONDecodeError:
        form_fields = []
    try:
        output_fields = json.loads(output_fields_json)
    except json.JSONDecodeError:
        output_fields = []

    if workflow_type == "speech_to_text":
        recipe = _build_recipe(
            ["audio"],
            file_config={
                "accept": "audio/*",
                "max_size_mb": 50,
                "label": "Audio recording",
                "required": True,
            },
        )
    else:
        # text_transformation, tool, workflow_trigger, custom
        recipe = _build_recipe(sources, form_fields if form_fields else None,
                               output_fields if output_fields else None)

    parsed_category_id = UUID(category_id) if category_id else None

    workflow = await service.update_workflow(
        db=db,
        slug=slug,
        name=name,
        description=description,
        category_id=parsed_category_id,
        workflow_type=workflow_type or None,
        recipe=recipe,
        output_action=output_action,
        default_hotkey=default_hotkey or None,
        timeout_seconds=timeout_seconds,
        is_active=is_active == "on",
        prompt_template=prompt_template or None,
        temperature=temperature,
        llm_model_id=parsed_llm_model_id,
        stt_model_id=parsed_stt_model_id,
        tool_id=parsed_tool_id,
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




# ============================================================
# Tool Admin Routes
# ============================================================


@router.get("/tools", response_class=HTMLResponse)
async def tools_list(request: Request, db: DbSession):
    """Tool overview page."""
    result = await db.execute(
        select(Tool).options(selectinload(Tool.workflows)).order_by(Tool.name)
    )
    tools = list(result.scalars().all())
    return templates.TemplateResponse("tools.html", {
        "request": request,
        "tools": tools,
        **_flash_context(request),
    })


@router.get("/tools/new", response_class=HTMLResponse)
async def new_tool_form(request: Request):
    """Show create tool form."""
    return templates.TemplateResponse("tool_form.html", {
        "request": request,
        "tool": None,
        "edit_mode": False,
    })


@router.post("/tools")
async def create_tool(
    request: Request,
    db: DbSession,
    name: str = Form(...),
    tool_type: str = Form(...),
    endpoint_url: str = Form(""),
    http_method: str = Form("POST"),
    headers: str = Form(""),
    payload_template: str = Form(""),
    response_mapping: str = Form(""),
    timeout: int = Form(120),
    description: str = Form(""),
    input_schema: str = Form(""),
    output_schema: str = Form(""),
    # n8n-specific fields
    n8n_base_url: str = Form(""),
    n8n_api_key: str = Form(""),
    n8n_flow_id: str = Form(""),
):
    """Register a new tool."""
    if endpoint_url:
        validate_provider_url(endpoint_url)
    if n8n_base_url:
        validate_provider_url(n8n_base_url)

    # Parse JSON fields
    parsed_headers = None
    if headers.strip():
        try:
            parsed_headers = json.loads(headers)
        except json.JSONDecodeError:
            parsed_headers = {}
            for line in headers.strip().split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    parsed_headers[k.strip()] = v.strip()

    parsed_input_schema = None
    if input_schema.strip():
        try:
            parsed_input_schema = json.loads(input_schema)
        except json.JSONDecodeError:
            pass

    parsed_output_schema = None
    if output_schema.strip():
        try:
            parsed_output_schema = json.loads(output_schema)
        except json.JSONDecodeError:
            pass

    tool = Tool(
        name=name,
        tool_type=tool_type,
        endpoint_url=endpoint_url or None,
        http_method=http_method,
        headers=parsed_headers,
        payload_template=payload_template or None,
        response_mapping=response_mapping or None,
        timeout=timeout,
        description=description or None,
        input_schema=parsed_input_schema,
        output_schema=parsed_output_schema,
        n8n_base_url=n8n_base_url or None,
        n8n_api_key=encrypt_api_key(n8n_api_key) if n8n_api_key else None,
        n8n_flow_id=n8n_flow_id or None,
    )
    db.add(tool)
    await db.commit()
    return RedirectResponse(f"/admin/tools/{tool.id}?flash=created", status_code=303)


@router.get("/tools/{tool_id}", response_class=HTMLResponse)
async def tool_detail(request: Request, tool_id: UUID, db: DbSession):
    """Show tool detail page."""
    tool = await db.get(Tool, tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    # Get linked workflows
    result = await db.execute(
        select(Workflow).where(
            Workflow.tool_id == tool_id,
        ).order_by(Workflow.name)
    )
    linked_workflows = list(result.scalars().all())

    return templates.TemplateResponse("tool_detail.html", {
        "request": request,
        "tool": tool,
        "linked_workflows": linked_workflows,
        **_flash_context(request),
    })


@router.get("/tools/{tool_id}/edit", response_class=HTMLResponse)
async def edit_tool_form(request: Request, tool_id: UUID, db: DbSession):
    """Show edit tool form."""
    tool = await db.get(Tool, tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    return templates.TemplateResponse("tool_form.html", {
        "request": request,
        "tool": tool,
        "edit_mode": True,
    })


@router.post("/tools/{tool_id}/update")
async def update_tool(
    request: Request,
    tool_id: UUID,
    db: DbSession,
    name: str = Form(...),
    tool_type: str = Form(...),
    endpoint_url: str = Form(""),
    http_method: str = Form("POST"),
    headers: str = Form(""),
    payload_template: str = Form(""),
    response_mapping: str = Form(""),
    timeout: int = Form(120),
    description: str = Form(""),
    input_schema: str = Form(""),
    output_schema: str = Form(""),
    is_active: str = Form("off"),
    # n8n-specific fields
    n8n_base_url: str = Form(""),
    n8n_api_key: str = Form(""),
    n8n_flow_id: str = Form(""),
):
    """Update a tool."""
    if endpoint_url:
        validate_provider_url(endpoint_url)
    if n8n_base_url:
        validate_provider_url(n8n_base_url)

    tool = await db.get(Tool, tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    tool.name = name
    tool.tool_type = tool_type
    tool.endpoint_url = endpoint_url or None
    tool.http_method = http_method
    tool.timeout = timeout
    tool.description = description or None
    tool.is_active = is_active == "on"
    tool.payload_template = payload_template or None
    tool.response_mapping = response_mapping or None
    tool.n8n_base_url = n8n_base_url or None
    tool.n8n_flow_id = n8n_flow_id or None

    if n8n_api_key:
        tool.n8n_api_key = encrypt_api_key(n8n_api_key)

    # Parse JSON fields
    if headers.strip():
        try:
            tool.headers = json.loads(headers)
        except json.JSONDecodeError:
            parsed = {}
            for line in headers.strip().split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    parsed[k.strip()] = v.strip()
            tool.headers = parsed
    else:
        tool.headers = None

    if input_schema.strip():
        try:
            tool.input_schema = json.loads(input_schema)
        except json.JSONDecodeError:
            pass
    else:
        tool.input_schema = None

    if output_schema.strip():
        try:
            tool.output_schema = json.loads(output_schema)
        except json.JSONDecodeError:
            pass
    else:
        tool.output_schema = None

    await db.commit()
    return RedirectResponse(f"/admin/tools/{tool_id}?flash=updated", status_code=303)


@router.post("/tools/{tool_id}/delete")
async def delete_tool(tool_id: UUID, db: DbSession):
    """Delete a tool."""
    tool = await db.get(Tool, tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    await db.delete(tool)
    await db.commit()
    return RedirectResponse("/admin/tools?flash=deleted", status_code=303)


@router.post("/tools/{tool_id}/health-check", response_class=HTMLResponse)
async def tool_health_check(request: Request, tool_id: UUID, db: DbSession):
    """HTMX: Run health check for a tool and return partial."""
    from datetime import datetime, timezone
    import httpx

    tool = await db.get(Tool, tool_id)
    if not tool:
        return templates.TemplateResponse("partials/health_result.html", {
            "request": request, "healthy": False, "message": "Tool not found",
        })

    try:
        url = tool.endpoint_url or tool.n8n_base_url
        if not url:
            raise Exception("No URL configured")
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            healthy = resp.status_code < 500
        tool.health_status = "healthy" if healthy else "unhealthy"
        tool.last_health_check = datetime.now(timezone.utc)
        await db.flush()
        return templates.TemplateResponse("partials/health_result.html", {
            "request": request,
            "healthy": healthy,
            "message": "" if healthy else f"HTTP {resp.status_code}",
        })
    except Exception as e:
        tool.health_status = "unhealthy"
        tool.last_health_check = datetime.now(timezone.utc)
        await db.flush()
        return templates.TemplateResponse("partials/health_result.html", {
            "request": request,
            "healthy": False,
            "message": str(e),
        })


@router.post("/tools/discover-runner", response_class=HTMLResponse)
async def discover_runner_tools(request: Request, db: DbSession):
    """HTMX: Discover tools from the Ancroo Runner and return partial."""
    try:
        settings = get_settings()
        report = await sync_tools_from_runner(db, settings.runner_base_url)
        await db.commit()
        return HTMLResponse(
            f'<div class="text-xs bg-green-50 text-green-700 border border-green-200 rounded p-2">'
            f'Discovery complete: {report.get("created", 0)} created, '
            f'{report.get("updated", 0)} updated, '
            f'{report.get("unchanged", 0)} unchanged.</div>'
        )
    except RunnerDiscoveryError as e:
        return HTMLResponse(
            f'<div class="text-xs bg-red-50 text-red-700 border border-red-200 rounded p-2">'
            f'Discovery failed: {e}</div>'
        )


# ============================================================
# LLM Model Admin Routes
# ============================================================


@router.get("/llm-models", response_class=HTMLResponse)
async def llm_models_list(request: Request, db: DbSession):
    """LLM model overview page."""
    from src.integrations.llm_providers import LLM_PROVIDERS_BY_KEY
    result = await db.execute(
        select(LLMModel).options(selectinload(LLMModel.workflows)).order_by(LLMModel.name)
    )
    llm_models = list(result.scalars().all())
    return templates.TemplateResponse("llm_models.html", {
        "request": request,
        "models": llm_models,
        "providers_by_key": LLM_PROVIDERS_BY_KEY,
        **_flash_context(request),
    })


@router.get("/llm-models/new", response_class=HTMLResponse)
async def new_llm_model_form(request: Request):
    """Show create LLM model form."""
    from src.integrations.llm_providers import LLM_PROVIDERS
    return templates.TemplateResponse("llm_model_form.html", {
        "request": request,
        "model": None,
        "edit_mode": False,
        "providers": LLM_PROVIDERS,
    })


@router.get("/llm-models/probe-models", response_class=HTMLResponse)
async def llm_model_probe_models(
    request: Request,
    provider_type: str = Query("ollama"),
    base_url: str = Query(""),
    api_key: str = Query(""),
    endpoint_models: str = Query(""),
):
    """HTMX: Probe available models using form field values (before model is saved)."""
    if not base_url:
        return HTMLResponse('<option value="">-- enter Base URL first --</option>')
    try:
        validate_provider_url(base_url)
    except HTTPException:
        return HTMLResponse('<option value="">-- invalid URL --</option>')
    try:
        models = await list_llm_models(base_url, provider_type, api_key or None,
                                       endpoint_models or None)
    except LLMError:
        return HTMLResponse('<option value="">-- could not reach provider --</option>')
    if not models:
        return HTMLResponse('<option value="">-- no models found --</option>')
    options = '<option value="">-- select a model --</option>'
    for model in models:
        options += f'<option value="{model}">{model}</option>'
    return HTMLResponse(options)


@router.post("/llm-models")
async def create_llm_model(
    request: Request,
    db: DbSession,
    provider_type: str = Form(...),
    name: str = Form(...),
    base_url: str = Form(...),
    endpoint_execute: str = Form("/v1/chat/completions"),
    endpoint_models: str = Form("/v1/models"),
    api_key: str = Form(""),
    model_id: str = Form(...),
    default_temperature: float = Form(0.3),
    config: str = Form(""),
):
    """Create a new LLM model."""
    validate_provider_url(base_url)

    parsed_config = None
    if config.strip():
        try:
            parsed_config = json.loads(config)
        except json.JSONDecodeError:
            pass

    llm_model = LLMModel(
        provider_type=provider_type,
        name=name,
        base_url=base_url,
        endpoint_execute=endpoint_execute,
        endpoint_models=endpoint_models,
        api_key=encrypt_api_key(api_key) if api_key else None,
        model_id=model_id,
        default_temperature=default_temperature,
        config=parsed_config,
    )
    db.add(llm_model)
    await db.commit()
    return RedirectResponse(f"/admin/llm-models/{llm_model.id}?flash=created", status_code=303)


@router.get("/llm-models/{model_id}", response_class=HTMLResponse)
async def llm_model_detail(request: Request, model_id: UUID, db: DbSession):
    """Show LLM model detail page."""
    llm_model = await db.get(LLMModel, model_id)
    if not llm_model:
        raise HTTPException(status_code=404, detail="LLM model not found")

    from src.integrations.llm_providers import LLM_PROVIDERS_BY_KEY
    result = await db.execute(
        select(Workflow)
        .where(Workflow.llm_model_id == model_id)
        .order_by(Workflow.name)
    )
    linked_workflows = list(result.scalars().all())

    return templates.TemplateResponse("llm_model_detail.html", {
        "request": request,
        "model": llm_model,
        "linked_workflows": linked_workflows,
        "providers_by_key": LLM_PROVIDERS_BY_KEY,
        **_flash_context(request),
    })


@router.get("/llm-models/{model_id}/edit", response_class=HTMLResponse)
async def edit_llm_model_form(request: Request, model_id: UUID, db: DbSession):
    """Show edit LLM model form."""
    from src.integrations.llm_providers import LLM_PROVIDERS
    llm_model = await db.get(LLMModel, model_id)
    if not llm_model:
        raise HTTPException(status_code=404, detail="LLM model not found")
    return templates.TemplateResponse("llm_model_form.html", {
        "request": request,
        "model": llm_model,
        "edit_mode": True,
        "providers": LLM_PROVIDERS,
    })


@router.post("/llm-models/{model_id}/update")
async def update_llm_model(
    request: Request,
    model_id: UUID,
    db: DbSession,
    name: str = Form(...),
    base_url: str = Form(...),
    endpoint_execute: str = Form("/v1/chat/completions"),
    endpoint_models: str = Form("/v1/models"),
    api_key: str = Form(""),
    model_id_field: str = Form(..., alias="model_id_field"),
    default_temperature: float = Form(0.3),
    config: str = Form(""),
    is_active: str = Form("off"),
):
    """Update an LLM model."""
    validate_provider_url(base_url)
    llm_model = await db.get(LLMModel, model_id)
    if not llm_model:
        raise HTTPException(status_code=404, detail="LLM model not found")

    llm_model.name = name
    llm_model.base_url = base_url
    llm_model.endpoint_execute = endpoint_execute
    llm_model.endpoint_models = endpoint_models
    if api_key:
        llm_model.api_key = encrypt_api_key(api_key)
    llm_model.model_id = model_id_field
    llm_model.default_temperature = default_temperature
    llm_model.is_active = is_active == "on"

    if config.strip():
        try:
            llm_model.config = json.loads(config)
        except json.JSONDecodeError:
            pass
    else:
        llm_model.config = None

    await db.commit()
    return RedirectResponse(f"/admin/llm-models/{model_id}?flash=updated", status_code=303)


@router.post("/llm-models/{model_id}/delete")
async def delete_llm_model(model_id: UUID, db: DbSession):
    """Delete an LLM model."""
    llm_model = await db.get(LLMModel, model_id)
    if not llm_model:
        raise HTTPException(status_code=404, detail="LLM model not found")
    await db.delete(llm_model)
    await db.commit()
    return RedirectResponse("/admin/llm-models?flash=deleted", status_code=303)


@router.post("/llm-models/{model_id}/health-check", response_class=HTMLResponse)
async def llm_model_health_check(request: Request, model_id: UUID, db: DbSession):
    """HTMX: Run health check and return partial."""
    from datetime import datetime, timezone
    llm_model = await db.get(LLMModel, model_id)
    if not llm_model:
        return templates.TemplateResponse("partials/health_result.html", {
            "request": request, "healthy": False, "message": "LLM model not found",
        })
    result = await check_llm_health(llm_model)
    llm_model.health_status = "healthy" if result.get("healthy") else "unhealthy"
    llm_model.last_health_check = datetime.now(timezone.utc)
    await db.flush()
    return templates.TemplateResponse("partials/health_result.html", {
        "request": request,
        "healthy": result.get("healthy", False),
        "message": result.get("error", ""),
    })


@router.get("/llm-models/{model_id}/discover-models", response_class=HTMLResponse)
async def llm_model_discover_models(request: Request, model_id: UUID, db: DbSession):
    """HTMX: Fetch available models from LLM provider and return partial."""
    llm_model = await db.get(LLMModel, model_id)
    if not llm_model:
        return HTMLResponse('<p class="text-xs text-red-600">LLM model not found</p>')
    try:
        models = await list_llm_models(llm_model.base_url, llm_model.provider_type,
                                       decrypt_api_key(llm_model.api_key) if llm_model.api_key else None,
                                       llm_model.endpoint_models)
    except LLMError as e:
        return HTMLResponse(
            f'<p class="text-xs text-red-600">Failed to load models: {e}</p>'
        )
    return templates.TemplateResponse("partials/llm_models.html", {
        "request": request,
        "models": models,
        "model_id": model_id,
    })


# ============================================================
# STT Model Admin Routes
# ============================================================


@router.get("/stt-models", response_class=HTMLResponse)
async def stt_models_list(request: Request, db: DbSession):
    """STT model overview page."""
    result = await db.execute(
        select(STTModel).options(selectinload(STTModel.workflows)).order_by(STTModel.name)
    )
    stt_models = list(result.scalars().all())
    return templates.TemplateResponse("stt_models.html", {
        "request": request,
        "models": stt_models,
        **_flash_context(request),
    })


@router.get("/stt-models/new", response_class=HTMLResponse)
async def new_stt_model_form(request: Request):
    """Show create STT model form."""
    return templates.TemplateResponse("stt_model_form.html", {
        "request": request,
        "model": None,
        "edit_mode": False,
    })


@router.post("/stt-models")
async def create_stt_model(
    request: Request,
    db: DbSession,
    provider_type: str = Form(...),
    name: str = Form(...),
    base_url: str = Form(...),
    api_key: str = Form(""),
    model_id: str = Form(...),
    default_language: str = Form(""),
    config: str = Form(""),
    is_default: str = Form("off"),
):
    """Create a new STT model."""
    validate_provider_url(base_url)

    parsed_config = None
    if config.strip():
        try:
            parsed_config = json.loads(config)
        except json.JSONDecodeError:
            pass

    stt_model = STTModel(
        provider_type=provider_type,
        name=name,
        base_url=base_url,
        api_key=encrypt_api_key(api_key) if api_key else None,
        model_id=model_id,
        default_language=default_language.strip() or None,
        config=parsed_config,
        is_default=is_default == "on",
    )
    db.add(stt_model)
    await db.commit()
    return RedirectResponse(f"/admin/stt-models/{stt_model.id}?flash=created", status_code=303)


@router.get("/stt-models/{model_id}", response_class=HTMLResponse)
async def stt_model_detail(request: Request, model_id: UUID, db: DbSession):
    """Show STT model detail page."""
    stt_model = await db.get(STTModel, model_id)
    if not stt_model:
        raise HTTPException(status_code=404, detail="STT model not found")

    result = await db.execute(
        select(Workflow)
        .where(Workflow.stt_model_id == model_id)
        .order_by(Workflow.name)
    )
    linked_workflows = list(result.scalars().all())

    return templates.TemplateResponse("stt_model_detail.html", {
        "request": request,
        "model": stt_model,
        "linked_workflows": linked_workflows,
        **_flash_context(request),
    })


@router.get("/stt-models/{model_id}/edit", response_class=HTMLResponse)
async def edit_stt_model_form(request: Request, model_id: UUID, db: DbSession):
    """Show edit STT model form."""
    stt_model = await db.get(STTModel, model_id)
    if not stt_model:
        raise HTTPException(status_code=404, detail="STT model not found")
    return templates.TemplateResponse("stt_model_form.html", {
        "request": request,
        "model": stt_model,
        "edit_mode": True,
    })


@router.post("/stt-models/{model_id}/update")
async def update_stt_model(
    request: Request,
    model_id: UUID,
    db: DbSession,
    name: str = Form(...),
    base_url: str = Form(...),
    api_key: str = Form(""),
    model_id_field: str = Form(..., alias="model_id_field"),
    default_language: str = Form(""),
    config: str = Form(""),
    is_active: str = Form("off"),
    is_default: str = Form("off"),
):
    """Update an STT model."""
    validate_provider_url(base_url)
    stt_model = await db.get(STTModel, model_id)
    if not stt_model:
        raise HTTPException(status_code=404, detail="STT model not found")

    stt_model.name = name
    stt_model.base_url = base_url
    if api_key:
        stt_model.api_key = encrypt_api_key(api_key)
    stt_model.model_id = model_id_field
    stt_model.default_language = default_language.strip() or None
    stt_model.is_active = is_active == "on"
    stt_model.is_default = is_default == "on"

    if config.strip():
        try:
            stt_model.config = json.loads(config)
        except json.JSONDecodeError:
            pass
    else:
        stt_model.config = None

    await db.commit()
    return RedirectResponse(f"/admin/stt-models/{model_id}?flash=updated", status_code=303)


@router.post("/stt-models/{model_id}/delete")
async def delete_stt_model(model_id: UUID, db: DbSession):
    """Delete an STT model."""
    stt_model = await db.get(STTModel, model_id)
    if not stt_model:
        raise HTTPException(status_code=404, detail="STT model not found")
    await db.delete(stt_model)
    await db.commit()
    return RedirectResponse("/admin/stt-models?flash=deleted", status_code=303)


@router.post("/stt-models/{model_id}/health-check", response_class=HTMLResponse)
async def stt_model_health_check(request: Request, model_id: UUID, db: DbSession):
    """HTMX: Run health check and return partial."""
    from datetime import datetime, timezone
    stt_model = await db.get(STTModel, model_id)
    if not stt_model:
        return templates.TemplateResponse("partials/health_result.html", {
            "request": request, "healthy": False, "message": "STT model not found",
        })
    result = await check_stt_health(stt_model)
    stt_model.health_status = "healthy" if result.get("healthy") else "unhealthy"
    stt_model.last_health_check = datetime.now(timezone.utc)
    await db.flush()
    return templates.TemplateResponse("partials/health_result.html", {
        "request": request,
        "healthy": result.get("healthy", False),
        "message": result.get("error", ""),
    })


@router.get("/stt-models/{model_id}/discover-models", response_class=HTMLResponse)
async def stt_model_discover_models(request: Request, model_id: UUID, db: DbSession):
    """HTMX: Fetch available models from STT provider and return partial."""
    stt_model = await db.get(STTModel, model_id)
    if not stt_model:
        return HTMLResponse('<p class="text-xs text-red-600">STT model not found</p>')
    try:
        models = await list_stt_models(stt_model.base_url)
    except STTError as e:
        return HTMLResponse(
            f'<p class="text-xs text-red-600">Failed to load models: {e}</p>'
        )
    return templates.TemplateResponse("partials/stt_models.html", {
        "request": request,
        "models": models,
        "model_id": model_id,
    })


# --- Categories ---


@router.get("/categories", response_class=HTMLResponse)
async def categories_list(request: Request, db: DbSession):
    """List all categories."""
    categories = await service.list_categories(db)
    return templates.TemplateResponse("categories.html", {
        "request": request,
        "categories": categories,
        **_flash_context(request),
    })


@router.get("/categories/new", response_class=HTMLResponse)
async def new_category_form(request: Request):
    """Show category creation form."""
    return templates.TemplateResponse("category_form.html", {
        "request": request,
        "category": None,
        "edit_mode": False,
    })


@router.post("/categories")
async def create_category(request: Request, db: DbSession, name: str = Form(...), icon: str = Form("\U0001f527")):
    """Create a new category."""
    existing = await service.get_category_by_name(db, name)
    if existing:
        return templates.TemplateResponse("category_form.html", {
            "request": request,
            "category": None,
            "edit_mode": False,
            "flash_message": f"Category '{name}' already exists.",
            "flash_type": "error",
        })
    await service.create_category(db, name=name, icon=icon)
    await db.commit()
    return RedirectResponse("/admin/categories?flash=created", status_code=303)


@router.get("/categories/{category_id}/edit", response_class=HTMLResponse)
async def edit_category_form(request: Request, category_id: UUID, db: DbSession):
    """Show category edit form."""
    category = await service.get_category(db, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    return templates.TemplateResponse("category_form.html", {
        "request": request,
        "category": category,
        "edit_mode": True,
    })


@router.post("/categories/{category_id}/update")
async def update_category_route(
    request: Request, category_id: UUID, db: DbSession,
    name: str = Form(...), icon: str = Form("\U0001f527"),
):
    """Update a category."""
    category = await service.update_category(db, category_id, name=name, icon=icon)
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")
    await db.commit()
    return RedirectResponse("/admin/categories?flash=updated", status_code=303)


@router.post("/categories/{category_id}/delete")
async def delete_category_route(request: Request, category_id: UUID, db: DbSession):
    """Delete a category (only if no workflows assigned)."""
    success, message = await service.delete_category(db, category_id)
    if not success:
        categories = await service.list_categories(db)
        return templates.TemplateResponse("categories.html", {
            "request": request,
            "categories": categories,
            "flash_message": message,
            "flash_type": "error",
        })
    await db.commit()
    return RedirectResponse("/admin/categories?flash=deleted", status_code=303)


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
