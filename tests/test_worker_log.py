"""Tests for the file-based worker run log (14.3 / 15 observability)."""

import json

import pytest

from app.libs.worker_log import record_worker_run


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    from main.config import settings

    monkeypatch.setattr(settings, "LOG_DIR", tmp_path)
    return tmp_path


def _read_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_record_worker_run_writes_ok_entry_with_result(log_dir):
    with record_worker_run("test.task") as run:
        run.result = {"expired": 3}

    entries = _read_lines(log_dir / "worker_runs.log")
    assert len(entries) == 1
    entry = entries[0]
    assert entry["task"] == "test.task"
    assert entry["status"] == "ok"
    assert entry["result"] == {"expired": 3}
    assert "started_at" in entry
    assert "duration_seconds" in entry


def test_record_worker_run_writes_error_entry_and_reraises(log_dir):
    with pytest.raises(ValueError):
        with record_worker_run("test.task"):
            raise ValueError("boom")

    entries = _read_lines(log_dir / "worker_runs.log")
    assert len(entries) == 1
    entry = entries[0]
    assert entry["task"] == "test.task"
    assert entry["status"] == "error"
    assert entry["error"] == "boom"
    assert "result" not in entry


def test_record_worker_run_appends_multiple_entries(log_dir):
    with record_worker_run("a"):
        pass
    with record_worker_run("b"):
        pass

    entries = _read_lines(log_dir / "worker_runs.log")
    assert [e["task"] for e in entries] == ["a", "b"]


def test_write_swallows_oserror_rather_than_failing_the_task(monkeypatch):
    """Observability must never be why a worker task fails -- a disk
    error writing the log must not propagate out of record_worker_run."""
    import app.libs.worker_log as worker_log_module

    def _raise():
        raise OSError("disk full")

    monkeypatch.setattr(worker_log_module, "_log_path", _raise)

    worker_log_module._write({"task": "x"})  # must not raise
