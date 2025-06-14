from __future__ import annotations

import asyncio
import json
from datetime import datetime

from app.worker.celery_app import celery_app, RetryableTask
from app.utils.logging import task_with_correlation
from app.utils.task_protection import prevent_duplicate_task
from app.core.supabase_client import supabase
from app.api.routes.kb import _optimize_kb_internal as optimize_logic

# NOTE: We reuse the existing optimize_knowledge_base async function that performs the heavy
# optimisation logic. This keeps the behaviour identical while shifting execution to a
# background queue. In a future refactor the algorithm can be moved to a dedicated service
# module, but this avoids code duplication for now.


@celery_app.task(bind=True, base=RetryableTask, queue="optimize", soft_time_limit=3600, time_limit=3660)
@task_with_correlation
@prevent_duplicate_task("optimize", lambda kb_id, *_, **__: kb_id)  # one optimise job per KB
def run_optimize_task(self, kb_id: str, threshold: float = 0.85):
    """Background Celery task that performs knowledge-base optimisation for the given KB.

    The task ID is used as the primary key in `kb_optimization_jobs`. The task updates that
    table when it starts, on each major stage, and upon completion or failure so that the
    API layer can expose real-time progress to the Front-End.
    """
    task_id = self.request.id

    # Helper to update job row
    def _update_job(**fields):
        fields["updated_at"] = datetime.utcnow().isoformat()
        try:
            supabase.table("kb_optimization_jobs").update(fields).eq("id", task_id).execute()
        except Exception:
            # Table might not exist yet; ignore failures so task continues
            pass

    # Mark as running
    _update_job(status="running", progress=json.dumps({"stage": "initialising", "details": "Starting optimisation"}))

    try:
        # Run the existing async optimiser inside a fresh event loop
        result = asyncio.run(optimize_logic(kb_id))

        # Persist final stats
        _update_job(status="completed", stats=json.dumps(result.get("stats", {})), progress=json.dumps({"stage": "completed", "details": result.get("message", "Completed")}))
        return result
    except Exception as exc:
        # Record failure
        _update_job(status="failed", error=str(exc))
        raise 