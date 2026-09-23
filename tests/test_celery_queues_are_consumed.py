"""Every queue a task is sent to must be a queue a worker listens on.

A Celery task whose queue nobody consumes does not fail. It is accepted,
written to the broker, and sits there. The caller sees a successful
`.delay()`, the logs are clean, and nothing arrives -- which is how the
test server ended up with 66 undelivered notifications going back six days,
including push for likes and messages, while every other queue drained
normally.

The queue list lives in a deploy command rather than in the code, so
nothing connected the two: adding `queue="notifications"` to a task and
adding `notifications` to `-Q` are separate edits in separate files, and
the second one is easy to forget and impossible to notice. This is the
thing that notices.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Where a task can say which queue it wants.
TASK_QUEUE = re.compile(r'queue\s*=\s*"([a-z_]+)"')
# Where the beat schedule says it, in the options dict.
BEAT_QUEUE = re.compile(r'"queue"\s*:\s*"([a-z_]+)"')
# Where a worker says what it will consume.
WORKER_QUEUES = re.compile(r"worker\b[^\n]*?-Q\s+([a-z_,]+)")

WORKER_COMMAND_FILES = [
    "docker-compose.production.yml",
    "docker-compose.dev.yml",
]


def queues_tasks_use() -> set:
    """Every queue anything in the app sends work to."""
    found = set()
    for path in (ROOT / "app").rglob("*.py"):
        found |= set(TASK_QUEUE.findall(path.read_text()))
    for path in (ROOT / "main").rglob("*.py"):
        text = path.read_text()
        found |= set(TASK_QUEUE.findall(text))
        found |= set(BEAT_QUEUE.findall(text))
    return found


def queues_a_worker_consumes(filename: str) -> set:
    text = (ROOT / filename).read_text()
    consumed = set()
    for group in WORKER_QUEUES.findall(text):
        consumed |= {q for q in group.split(",") if q}
    return consumed


class TestNoQueueIsOrphaned:
    @pytest.mark.parametrize("filename", WORKER_COMMAND_FILES)
    def test_every_queue_in_use_has_a_consumer(self, filename):
        used = queues_tasks_use()
        consumed = queues_a_worker_consumes(filename)
        orphaned = used - consumed
        assert not orphaned, (
            f"{filename} starts no worker for {sorted(orphaned)}. Tasks sent "
            f"there are accepted by the broker and never run: no error, no "
            f"log, nothing delivered. Add them to -Q."
        )

    @pytest.mark.parametrize("filename", WORKER_COMMAND_FILES)
    def test_no_worker_waits_on_a_queue_nothing_uses(self, filename):
        # The other direction is only untidy, not broken -- but it is the
        # symptom of the same drift, and a queue nobody sends to is usually
        # a rename nobody finished.
        stale = queues_a_worker_consumes(filename) - queues_tasks_use()
        assert (
            not stale
        ), f"{filename} consumes {sorted(stale)}, which nothing sends to."

    def test_the_deploy_files_agree_with_each_other(self):
        lists = {f: queues_a_worker_consumes(f) for f in WORKER_COMMAND_FILES}
        assert len(set(map(frozenset, lists.values()))) == 1, (
            f"Worker queue lists have drifted apart: "
            f"{ {f: sorted(q) for f, q in lists.items()} }"
        )


class TestTheCheckItselfWorks:
    def test_it_finds_the_notifications_queue(self):
        # Guards against the regexes silently matching nothing, which would
        # make every assertion above pass for the wrong reason.
        used = queues_tasks_use()
        assert "notifications" in used
        assert len(used) >= 5

    def test_it_finds_a_worker_command(self):
        for filename in WORKER_COMMAND_FILES:
            assert queues_a_worker_consumes(filename), f"{filename}: no -Q found"
