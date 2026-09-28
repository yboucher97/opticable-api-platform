"""Explicitly configured, bounded scheduling. No account discovery or full scans."""
from __future__ import annotations

import os
import time
import threading
from pathlib import Path
from typing import Callable, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .delta_sync import DeltaSync
from .google_delta import GoogleDeltaAdapter
from .store import AutomationStore


class SyncJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["google.calendar", "google.drive", "google.gmail"]
    source_account: str = Field(min_length=1, max_length=255)
    stream: str = Field(min_length=1, max_length=255)
    mode: Literal["incremental", "backfill"] = "incremental"
    initial_cursor: str | None = Field(default=None, min_length=1, max_length=4096)
    poll_interval_seconds: int = Field(default=300, ge=30, le=86400)
    page_limit: int = Field(default=100, ge=1, le=100)
    enabled: bool = False


def load_jobs() -> list[SyncJob]:
    path = Path(os.getenv("OPTIBRAIN_SYNC_CONFIG", "config/automation/delta-sync.yaml"))
    if not path.exists():
        return []
    if path.stat().st_size > 65536:
        raise ValueError("sync configuration exceeds bounds")
    raw = yaml.safe_load(path.read_text()) or []
    if not isinstance(raw, list) or len(raw) > 100:
        raise ValueError("invalid sync configuration")
    jobs = [SyncJob.model_validate(item) for item in raw]
    keys = [(j.provider, j.source_account, j.stream, j.mode) for j in jobs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate sync configuration")
    return [job for job in jobs if job.enabled]


def initialize_jobs(store: AutomationStore) -> list[SyncJob]:
    jobs = load_jobs()
    sync = DeltaSync(store)
    for job in jobs:
        if job.mode == "backfill" and job.provider != "google.calendar":
            raise ValueError("only Calendar supports explicit backfill")
        sync.initialize(job.provider, job.source_account, job.stream, cursor=job.initial_cursor, mode=job.mode)
    return jobs


def sync_one_due(store: AutomationStore, jobs: list[SyncJob], access_token: Callable[[], str]) -> None:
    sync = DeltaSync(store)
    due = []
    for job in jobs:
        state = sync.snapshot(job.provider, job.source_account, job.stream, job.mode)
        if state and state["status"] not in {"failed", "resync_required"} and state["next_attempt_at"] <= time.time_ns() // 1000:
            due.append((state["updated_at"], job))
    if due:
        job = min(due, key=lambda pair: pair[0])[1]
        sync.cycle(job.provider, job.source_account, job.stream,
                   GoogleDeltaAdapter(job.provider, job.source_account, job.stream, access_token),
                   mode=job.mode, page_limit=job.page_limit, max_pages=1,
                   poll_interval=job.poll_interval_seconds)


class DeltaWorker:
    """One bounded polling thread, independently observable from run recovery."""

    def __init__(self, store: AutomationStore, access_token: Callable[[], str]) -> None:
        self.store, self.access_token = store, access_token
        self.jobs: list[SyncJob] = []
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._last_progress = time.monotonic()
        self._failures = 0

    def start(self, jobs: list[SyncJob]) -> None:
        if self._thread and self._thread.is_alive():
            raise RuntimeError("delta worker is already running")
        self.jobs = list(jobs)
        if not self.jobs:
            return
        self._stop.clear()
        self._last_progress = time.monotonic()
        self._thread = threading.Thread(target=self._run, name="automation-delta-sync", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                sync_one_due(self.store, self.jobs, self.access_token)
                with self._lock:
                    self._failures = 0
            except Exception as exc:
                # Persist a fixed diagnostic and stop after three unexpected
                # faults. Never print provider exception text or credentials.
                with self._lock:
                    self._failures += 1
                self.store.audit(category="delta_worker", action="cycle_failed", actor="delta-sync", success=False,
                                 metadata={"exception_type": type(exc).__name__})
            with self._lock:
                self._last_progress = time.monotonic()
                if self._failures >= 3:
                    return
            self._stop.wait(5)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def health(self) -> dict:
        with self._lock:
            alive = bool(self._thread and self._thread.is_alive())
            age = int(time.monotonic() - self._last_progress)
            enabled = bool(self.jobs)
            return {"enabled": enabled, "thread_alive": alive, "heartbeat_age_seconds": age,
                    "consecutive_failures": self._failures,
                    "healthy": not enabled or (alive and age < 180 and self._failures == 0)}
