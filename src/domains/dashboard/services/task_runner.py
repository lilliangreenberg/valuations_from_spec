"""Background CLI task execution with SSE streaming."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

ALLOWED_COMMANDS: dict[str, dict[str, Any]] = {
    "extract-companies": {
        "description": "Extract companies from Airtable",
        "group": "Data Extraction",
        "args": [],
    },
    "import-urls": {
        "description": "Import social media and blog URLs from Airtable",
        "group": "Data Extraction",
        "args": [],
    },
    "capture-snapshots": {
        "description": "Capture website snapshots",
        "group": "Data Extraction",
        "args": [
            {
                "name": "--use-batch-api",
                "type": "flag",
                "default": False,
                "label": "Use batch API (8x faster)",
            },
            {"name": "--batch-size", "type": "int", "default": 20, "label": "Batch size"},
        ],
    },
    "detect-changes": {
        "description": "Detect content changes between snapshots",
        "group": "Change Detection",
        "args": [
            {"name": "--limit", "type": "int", "default": "", "label": "Limit (companies)"},
        ],
    },
    "analyze-status": {
        "description": "Analyze company operational status",
        "group": "Change Detection",
        "args": [],
    },
    "backfill-significance": {
        "description": "Backfill significance analysis for existing records",
        "group": "Change Detection",
        "args": [
            {
                "name": "--dry-run",
                "type": "flag",
                "default": False,
                "label": "Dry run (preview only)",
            },
        ],
    },
    "analyze-baseline": {
        "description": "Run baseline signal analysis on snapshots",
        "group": "Change Detection",
        "args": [
            {"name": "--limit", "type": "int", "default": "", "label": "Limit (companies)"},
            {
                "name": "--dry-run",
                "type": "flag",
                "default": False,
                "label": "Dry run (preview only)",
            },
        ],
    },
    "discover-social-media": {
        "description": "Discover social media links from homepages",
        "group": "Social Media Discovery",
        "args": [
            {"name": "--batch-size", "type": "int", "default": 50, "label": "Batch size"},
            {"name": "--limit", "type": "int", "default": "", "label": "Limit (companies)"},
            {"name": "--company-id", "type": "int", "default": "", "label": "Company ID (single)"},
        ],
    },
    "search-news": {
        "description": "Search news for a single company",
        "group": "News Monitoring",
        "args": [
            {"name": "--company-name", "type": "str", "default": "", "label": "Company name"},
            {"name": "--company-id", "type": "int", "default": "", "label": "Company ID"},
        ],
    },
    "search-news-all": {
        "description": "Search news for all companies",
        "group": "News Monitoring",
        "args": [
            {"name": "--limit", "type": "int", "default": "", "label": "Limit (companies)"},
            {"name": "--max-workers", "type": "int", "default": 5, "label": "Parallel workers"},
        ],
    },
    "extract-leadership": {
        "description": "Extract leadership for a single company (opens Chrome)",
        "group": "Leadership Extraction",
        "args": [
            {"name": "--company-id", "type": "int", "default": "", "label": "Company ID"},
        ],
    },
    "extract-leadership-all": {
        "description": "Extract leadership for all companies (opens Chrome)",
        "group": "Leadership Extraction",
        "args": [
            {"name": "--limit", "type": "int", "default": "", "label": "Limit (companies)"},
        ],
    },
    "check-leadership-changes": {
        "description": "Re-extract leadership and report changes",
        "group": "Leadership Extraction",
        "args": [
            {"name": "--limit", "type": "int", "default": "", "label": "Limit (companies)"},
        ],
    },
}


@dataclass
class TaskRecord:
    """Record of a background CLI task."""

    task_id: str
    command: str
    args: list[str]
    status: str = "pending"  # pending, running, completed, failed, cancelled
    started_at: datetime | None = None
    completed_at: datetime | None = None
    output_lines: list[str] = field(default_factory=list)
    return_code: int | None = None

    @property
    def duration_seconds(self) -> float | None:
        """Duration in seconds if completed."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    @property
    def display_command(self) -> str:
        """Human-readable command string."""
        parts = [self.command, *self.args]
        return " ".join(parts)


class TaskRunner:
    """Manages background CLI command execution with SSE streaming."""

    def __init__(self, max_concurrent: int = 2) -> None:
        self._tasks: dict[str, TaskRecord] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._queues: dict[str, asyncio.Queue[str]] = {}
        self.max_concurrent = max_concurrent

    async def start_task(self, command: str, args: list[str]) -> str:
        """Start a CLI command as a background subprocess. Returns task_id."""
        if command not in ALLOWED_COMMANDS:
            msg = f"Command not allowed: {command}"
            raise ValueError(msg)

        task_id = str(uuid.uuid4())[:8]
        task = TaskRecord(
            task_id=task_id,
            command=command,
            args=args,
            status="running",
            started_at=datetime.now(UTC),
        )
        self._tasks[task_id] = task
        self._queues[task_id] = asyncio.Queue()

        full_cmd = ["uv", "run", "airtable-extractor", command, *args]
        logger.info("task_starting", task_id=task_id, command=full_cmd)

        process = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        self._processes[task_id] = process

        # Start reader coroutine
        asyncio.create_task(self._read_output(task_id, process))

        return task_id

    async def _read_output(self, task_id: str, process: asyncio.subprocess.Process) -> None:
        """Read process output line by line and forward to queue."""
        task = self._tasks[task_id]
        queue = self._queues[task_id]

        try:
            assert process.stdout is not None
            while True:
                line_bytes = await process.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").rstrip("\n")
                task.output_lines.append(line)
                await queue.put(line)
        except Exception as exc:
            error_line = f"[ERROR] Output read failed: {exc}"
            task.output_lines.append(error_line)
            await queue.put(error_line)

        # Wait for process to finish
        return_code = await process.wait()
        task.return_code = return_code
        task.completed_at = datetime.now(UTC)
        task.status = "completed" if return_code == 0 else "failed"

        # Signal end of stream
        await queue.put("")  # Empty string signals end

        logger.info(
            "task_completed",
            task_id=task_id,
            return_code=return_code,
            status=task.status,
        )

        # Cleanup process reference
        self._processes.pop(task_id, None)

    async def stream_task(self, task_id: str) -> Any:
        """Yield SSE events for a task's output."""
        queue = self._queues.get(task_id)
        task = self._tasks.get(task_id)

        if not queue or not task:
            yield {"event": "error", "data": f"Task {task_id} not found"}
            return

        # Replay buffered output first
        for line in task.output_lines:
            yield {"event": "output", "data": line}

        # If task already finished, send done event
        if task.status in ("completed", "failed", "cancelled"):
            yield {
                "event": "done",
                "data": f"status={task.status} return_code={task.return_code}",
            }
            return

        # Stream new output
        while True:
            try:
                line = await asyncio.wait_for(queue.get(), timeout=30.0)
                if line == "":  # End signal
                    yield {
                        "event": "done",
                        "data": f"status={task.status} return_code={task.return_code}",
                    }
                    return
                yield {"event": "output", "data": line}
            except TimeoutError:
                # Send keepalive
                yield {"event": "ping", "data": ""}

    def get_task(self, task_id: str) -> TaskRecord | None:
        """Get task status and buffered output."""
        return self._tasks.get(task_id)

    def get_task_history(self, limit: int = 20) -> list[TaskRecord]:
        """Recent tasks sorted by start time (newest first)."""
        tasks = sorted(
            self._tasks.values(),
            key=lambda t: t.started_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        return tasks[:limit]

    def get_running_count(self) -> int:
        """Number of currently running tasks."""
        return sum(1 for t in self._tasks.values() if t.status == "running")

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task by terminating its subprocess."""
        process = self._processes.get(task_id)
        task = self._tasks.get(task_id)

        if not process or not task or task.status != "running":
            return False

        try:
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except TimeoutError:
            process.kill()

        task.status = "cancelled"
        task.completed_at = datetime.now(UTC)
        task.return_code = -1

        logger.info("task_cancelled", task_id=task_id)
        self._processes.pop(task_id, None)
        return True

    async def cleanup(self) -> None:
        """Terminate all running processes. Called on shutdown."""
        for task_id in list(self._processes.keys()):
            await self.cancel_task(task_id)
        logger.info("task_runner_cleaned_up")
