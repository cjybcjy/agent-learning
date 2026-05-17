from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from sentinel.web.dependencies import get_scanner

logger = logging.getLogger(__name__)


class ScanTaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ScanTask:
    task_id: str
    status: ScanTaskStatus
    theme: str
    total: int = 0
    completed: int = 0
    reports: list = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


# In-memory task store (process-local)
_tasks: dict[str, ScanTask] = {}


def create_task(theme: str) -> str:
    task_id = str(uuid.uuid4())[:8]
    _tasks[task_id] = ScanTask(
        task_id=task_id, status=ScanTaskStatus.PENDING, theme=theme
    )
    return task_id


def get_task(task_id: str) -> ScanTask | None:
    return _tasks.get(task_id)


def run_scan_task(task_id: str, theme: str, target_roles: list[str] | None, policy_rating: str):
    task = _tasks.get(task_id)
    if task is None:
        return
    task.status = ScanTaskStatus.RUNNING
    try:
        scanner = get_scanner()
        result = scanner.scan_theme(
            theme_name=theme,
            target_roles=target_roles,
            policy_rating=policy_rating,
        )
        task.total = result.total_candidates
        task.completed = result.filtered_count
        task.reports = result.reports
        task.summary = result.summary
        task.status = ScanTaskStatus.COMPLETED
    except Exception as e:
        logger.exception("Scan task %s failed", task_id)
        task.status = ScanTaskStatus.FAILED
        task.error = str(e)
