from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Final

from domain.common import InvalidStateTransitionError, new_id, utcnow


class JobType(StrEnum):
    AI_RUN = "ai_run"
    FIRMWARE_BUILD = "firmware_build"
    FIRMWARE_DEPLOY = "firmware_deploy"  # host downloads, verifies sha256, writes UF2 over USB
    FIRMWARE_ROLLBACK = "firmware_rollback"  # redeploy the previous approved version (N-1)
    TEST_RUN = "test_run"
    DATA_ANALYSIS = "data_analysis"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_STATUSES


TERMINAL_STATUSES: Final = frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED})

_ALLOWED: Final[dict[JobStatus, frozenset[JobStatus]]] = {
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED, JobStatus.FAILED}),
    JobStatus.RUNNING: frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}),
    JobStatus.SUCCEEDED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}


@dataclass(frozen=True, slots=True)
class Job:
    """A tracked asynchronous operation (AI run, firmware build, test run, analysis).

    ``input_reference``/``output_reference`` point at stored objects (e.g. S3 keys); large
    inputs/outputs never live on the job row itself.
    """

    project_id: str
    job_type: JobType
    created_by: str
    id: str = field(default_factory=lambda: new_id("job"))
    device_id: str | None = None
    status: JobStatus = JobStatus.QUEUED
    input_reference: str | None = None
    output_reference: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_summary: str | None = None

    def transition(self, new_status: JobStatus, *, error_summary: str | None = None) -> Job:
        if new_status not in _ALLOWED[self.status]:
            raise InvalidStateTransitionError(
                f"job {self.id}: {self.status.value} -> {new_status.value} not allowed"
            )
        now = utcnow()
        return replace(
            self,
            status=new_status,
            started_at=now if new_status is JobStatus.RUNNING else self.started_at,
            completed_at=now if new_status.is_terminal else self.completed_at,
            error_summary=error_summary if new_status is JobStatus.FAILED else self.error_summary,
        )
