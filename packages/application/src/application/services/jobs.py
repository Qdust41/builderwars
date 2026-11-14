from __future__ import annotations

from application.ports import DeviceRepository, JobQueue, JobRepository
from application.services.authorization import Authorizer
from domain.common import NotFoundError
from domain.jobs import Job, JobType
from domain.projects import Permission


class JobService:
    def __init__(
        self,
        jobs: JobRepository,
        devices: DeviceRepository,
        queue: JobQueue,
        authorizer: Authorizer,
    ) -> None:
        self._jobs = jobs
        self._devices = devices
        self._queue = queue
        self._authorizer = authorizer

    def create_job(
        self,
        *,
        user_id: str,
        project_id: str,
        job_type: JobType,
        device_id: str | None = None,
        input_reference: str | None = None,
    ) -> Job:
        self._authorizer.require(user_id, project_id, Permission.CREATE_JOB)
        if device_id is not None:
            device = self._devices.get(device_id)
            if device is None or device.project_id != project_id:
                raise NotFoundError("device", device_id)
        job = Job(
            project_id=project_id,
            job_type=job_type,
            created_by=user_id,
            device_id=device_id,
            input_reference=input_reference,
        )
        # Persist first, then enqueue: a worker that receives the id can always load the job.
        # TODO: use a transactional outbox so a crash between the two cannot strand a job.
        self._jobs.add(job)
        self._queue.enqueue(job.id)
        return job

    def get_job(self, *, user_id: str, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise NotFoundError("job", job_id)
        try:
            self._authorizer.require(user_id, job.project_id, Permission.VIEW_PROJECT)
        except NotFoundError:
            raise NotFoundError("job", job_id) from None
        return job
