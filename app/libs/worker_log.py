"""File-based worker run log (14.3 / 15 observability).

Records every scheduled recovery/expiry worker's runs -- start time,
duration, result, and any exception -- so "did worker X run, and did it
fail" is answerable without either a DB table (this repo's Postgres is
already carrying enough) or a third-party error tracker/APM. The latter
is a real infra choice, deliberately deferred until Markt has live
traffic to justify the engineering (see the Implementation Checklist's
Phase 8 note) -- if that gap ever stops being "good enough," swap this
module's `_write` for a real provider's SDK call without touching any
call site, since every task only ever imports `record_worker_run`.

One JSON object per line (JSON Lines), append-only, under
settings.LOG_DIR alongside the existing markt.log. `.log` extension
deliberately, not `.jsonl` -- reuses the `*.log` .gitignore rule that
already excludes runtime logs from version control.
"""

import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from main.config import settings

logger = logging.getLogger(__name__)

WORKER_LOG_FILENAME = "worker_runs.log"


class WorkerRunResult:
    """Yielded by record_worker_run -- set `.result` to whatever the
    task's own return value/summary dict is, so it lands in the log
    entry alongside the timing/status fields."""

    def __init__(self):
        self.result = None


def _log_path():
    settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
    return settings.LOG_DIR / WORKER_LOG_FILENAME


def _write(entry: dict) -> None:
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except OSError:
        # Observability must never be why a worker task fails -- log and
        # move on rather than raising out of record_worker_run's __exit__.
        logger.exception(
            "Failed to write worker run log entry for %s", entry.get("task")
        )


@contextmanager
def record_worker_run(task_name: str):
    """Wrap a worker task body. Always writes one JSON line -- status
    "ok" with the yielded holder's `.result`, or status "error" with the
    exception's message -- then re-raises whatever the wrapped body
    raised. This only observes; it never swallows a real failure."""
    started_at = datetime.now(timezone.utc)
    start = time.monotonic()
    holder = WorkerRunResult()
    entry = {"task": task_name, "started_at": started_at.isoformat()}
    try:
        yield holder
    except Exception as exc:
        entry["status"] = "error"
        entry["error"] = str(exc)
        raise
    else:
        entry["status"] = "ok"
        entry["result"] = holder.result
    finally:
        entry["duration_seconds"] = round(time.monotonic() - start, 3)
        _write(entry)
