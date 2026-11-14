"""Process queued jobs (AI runs, firmware builds, test runs).

Queue messages carry only ``{"job_id": ...}``; the job row is the source of truth. Handling is
idempotent: a redelivered message for a job that is already running or finished is ignored.
Long-running work (builds, AI runs) belongs in ECS Fargate workers, not Lambda — this handler
is the dispatch boundary for both.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from application.ports import JobRepository
from domain.jobs import Job, JobStatus, JobType

log = logging.getLogger(__name__)


class JobMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    job_id: str


class JobExecutor(Protocol):
    """Runs one job type. Must be safe to retry. Returns an output reference (e.g. S3 key)."""

    def run(self, job: Job) -> str | None: ...


class BackgroundJobHandler:
    def __init__(self, jobs: JobRepository, executors: Mapping[JobType, JobExecutor]) -> None:
        self._jobs = jobs
        self._executors = executors

    def handle(self, message: JobMessage) -> Job | None:
        job = self._jobs.get(message.job_id)
        if job is None:
            log.warning("job %s not found; dropping message", message.job_id)
            return None
        if job.status is not JobStatus.QUEUED:
            # Duplicate delivery or already picked up. TODO: detect stuck RUNNING jobs with a
            # lease/heartbeat instead of trusting status alone.
            return job

        executor = self._executors.get(job.job_type)
        if executor is None:
            failed = job.transition(
                JobStatus.FAILED,
                error_summary=f"no executor for job type {job.job_type.value} (not implemented)",
            )
            self._jobs.save(failed)
            return failed

        running = job.transition(JobStatus.RUNNING)
        self._jobs.save(running)
        try:
            output = executor.run(running)
        except Exception as exc:
            failed = running.transition(JobStatus.FAILED, error_summary=type(exc).__name__)
            self._jobs.save(failed)
            return failed
        done = replace(running.transition(JobStatus.SUCCEEDED), output_reference=output)
        self._jobs.save(done)
        return done
