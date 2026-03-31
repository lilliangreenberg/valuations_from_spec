"""Operations panel routes for CLI command execution with SSE streaming."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response
from sse_starlette.sse import EventSourceResponse

from src.domains.dashboard.dependencies import get_task_runner, get_templates
from src.domains.dashboard.services.task_runner import ALLOWED_COMMANDS

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/", response_class=HTMLResponse)
async def operations_page(
    request: Request,
    command: str = "",
    company_id: str = "",
    task_runner: object = Depends(get_task_runner),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """Render the operations panel page."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.task_runner import TaskRunner

    tr = task_runner
    assert isinstance(tr, TaskRunner)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    history = tr.get_task_history(limit=20)
    running_count = tr.get_running_count()

    return tmpl.TemplateResponse(
        request,
        "operations.html",
        {
            "commands": ALLOWED_COMMANDS,
            "history": history,
            "running_count": running_count,
            "selected_command": command,
            "prefill_company_id": company_id,
        },
    )


@router.post("/run", response_class=HTMLResponse)
async def run_command(
    request: Request,
    command: str = Form(...),
    task_runner: object = Depends(get_task_runner),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """Start a CLI command as a background task."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.task_runner import TaskRunner

    tr = task_runner
    assert isinstance(tr, TaskRunner)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    if command not in ALLOWED_COMMANDS:
        return tmpl.TemplateResponse(
            request,
            "partials/task_progress.html",
            {"error": f"Unknown command: {command}", "task": None},
        )

    if tr.get_running_count() >= tr.max_concurrent:
        return tmpl.TemplateResponse(
            request,
            "partials/task_progress.html",
            {
                "error": f"Maximum concurrent tasks ({tr.max_concurrent}) reached. "
                "Wait for a task to complete.",
                "task": None,
            },
        )

    # Parse additional form data into CLI args
    form_data = await request.form()
    args = _build_args_from_form(command, dict(form_data))

    operator = getattr(request.state, "operator", None)
    task_id = await tr.start_task(command, args, operator=operator)
    task = tr.get_task(task_id)

    return tmpl.TemplateResponse(
        request,
        "partials/task_progress.html",
        {"task": task, "error": None},
    )


@router.get("/tasks/{task_id}/poll")
async def task_poll(
    request: Request,
    task_id: str,
    task_runner: object = Depends(get_task_runner),
) -> Response:
    """Lightweight poll endpoint. Returns HX-Refresh when the task is done."""
    from src.domains.dashboard.services.task_runner import TaskRunner

    tr = task_runner
    assert isinstance(tr, TaskRunner)

    task = tr.get_task(task_id)
    if task and task.status in ("completed", "failed", "cancelled"):
        return Response(status_code=204, headers={"HX-Refresh": "true"})
    return Response(status_code=204)


@router.get("/tasks/{task_id}/stream")
async def task_stream(
    request: Request,
    task_id: str,
    task_runner: object = Depends(get_task_runner),
) -> EventSourceResponse:
    """SSE endpoint: stream task output in real-time."""
    from src.domains.dashboard.services.task_runner import TaskRunner

    tr = task_runner
    assert isinstance(tr, TaskRunner)

    return EventSourceResponse(tr.stream_task(task_id))


@router.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_status(
    request: Request,
    task_id: str,
    task_runner: object = Depends(get_task_runner),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """HTMX partial: current task status and output."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.task_runner import TaskRunner

    tr = task_runner
    assert isinstance(tr, TaskRunner)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    task = tr.get_task(task_id)

    return tmpl.TemplateResponse(
        request,
        "partials/task_progress.html",
        {"task": task, "error": None if task else f"Task {task_id} not found"},
    )


@router.post("/tasks/{task_id}/cancel", response_class=HTMLResponse)
async def cancel_task(
    request: Request,
    task_id: str,
    task_runner: object = Depends(get_task_runner),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """Cancel a running task."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.task_runner import TaskRunner

    tr = task_runner
    assert isinstance(tr, TaskRunner)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    cancelled = await tr.cancel_task(task_id)
    task = tr.get_task(task_id)

    return tmpl.TemplateResponse(
        request,
        "partials/task_progress.html",
        {
            "task": task,
            "error": None if cancelled else f"Could not cancel task {task_id}",
        },
    )


@router.get("/partials/history", response_class=HTMLResponse)
async def task_history_partial(
    request: Request,
    task_runner: object = Depends(get_task_runner),
    templates: object = Depends(get_templates),
) -> HTMLResponse:
    """HTMX partial: recent task history."""
    from starlette.templating import Jinja2Templates

    from src.domains.dashboard.services.task_runner import TaskRunner

    tr = task_runner
    assert isinstance(tr, TaskRunner)
    tmpl = templates
    assert isinstance(tmpl, Jinja2Templates)

    history = tr.get_task_history(limit=20)

    return tmpl.TemplateResponse(
        request,
        "partials/task_history.html",
        {"history": history},
    )


def _build_args_from_form(command: str, form_data: dict[str, Any]) -> list[str]:
    """Build CLI argument list from form data based on command definition."""
    cmd_def = ALLOWED_COMMANDS.get(command, {})
    arg_defs = cmd_def.get("args", [])
    args: list[str] = []

    for arg_def in arg_defs:
        name = arg_def["name"]
        form_key = name.lstrip("-").replace("-", "_")
        value = form_data.get(form_key)

        if value is None or value == "":
            continue

        if arg_def["type"] == "flag":
            if str(value).lower() in ("true", "on", "1", "yes"):
                args.append(name)
        elif not name.startswith("-"):
            # Positional argument (no -- prefix)
            args.append(str(value))
        else:
            args.extend([name, str(value)])

    return args
