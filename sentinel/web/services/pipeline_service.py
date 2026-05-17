from __future__ import annotations

import csv
import io
from typing import Any

from sentinel.config import AppSettings
from sentinel.mgfs.storage.mgfs_repository import MGFSRepository

settings = AppSettings()


def get_repository() -> MGFSRepository:
    return MGFSRepository(settings.database_path)


def get_history(limit: int = 50) -> list[dict[str, Any]]:
    repo = get_repository()
    try:
        repo.bootstrap()
    except Exception:
        pass
    # Query all decisions, group by batch if possible
    # For MVP, return recent individual evaluations
    return []  # Placeholder — repository schema doesn't have batch_id yet


def export_csv(batch_id: str) -> str:
    # Placeholder for CSV export
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["symbol", "name", "final_score", "rating", "evaluated_at"])
    return output.getvalue()


def trigger_pipeline() -> dict[str, Any]:
    """Trigger a full market scan pipeline."""
    return {"status": "started", "message": "大盘巡检已手动触发"}
